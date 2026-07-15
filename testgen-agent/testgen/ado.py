"""Azure DevOps work item helpers for the test-generation pipeline."""

from __future__ import annotations

import base64
import html
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


_WORK_ITEM_ID_RE = re.compile(r"(?:AB#|ADO-|WI-)(\d+)", re.IGNORECASE)


def extract_work_item_id(text: str | None) -> Optional[str]:
    """Extract a numeric Azure DevOps work item id from commit/branch text.

    Supported conventions are intentionally conservative to avoid false
    positives from unrelated numbers:
    - AB#1234
    - ADO-1234
    - WI-1234
    """
    if not text:
        return None
    match = _WORK_ITEM_ID_RE.search(text)
    return match.group(1) if match else None


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p>\s*<p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_work_item_context(
    *,
    org_url: str,
    project: str,
    pat: str,
    work_item_id: str,
    timeout: int = 10,
) -> str:
    """Fetch a single ADO work item and format the useful fields for prompts.

    The function is intentionally best-effort: any API/auth/network issue
    returns a readable note instead of failing the entire generation run.
    """
    org_url = org_url.strip().rstrip("/")
    project = project.strip()
    pat = pat.strip()
    work_item_id = str(work_item_id).strip()

    if not org_url or not project or not pat or not work_item_id:
        return "Not available."

    url = (
        f"{org_url}/{project}/_apis/wit/workitems/{work_item_id}"
        "?$expand=relations&api-version=7.1-preview.3"
    )
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return f"Detected Azure DevOps work item {work_item_id}, but the API returned HTTP {exc.code}."
    except Exception as exc:  # pragma: no cover - best-effort network helper
        return f"Detected Azure DevOps work item {work_item_id}, but fetching details failed: {exc}."

    fields = payload.get("fields", {}) or {}
    title = fields.get("System.Title", "")
    state = fields.get("System.State", "")
    assigned_to = fields.get("System.AssignedTo", "")
    description = _strip_html(fields.get("System.Description", ""))
    acceptance = _strip_html(fields.get("Microsoft.VSTS.Common.AcceptanceCriteria", ""))
    tags = fields.get("System.Tags", "")
    tag_text = tags.replace(";", ", ") if isinstance(tags, str) else ""

    assigned_to_text = ""
    if isinstance(assigned_to, dict):
        assigned_to_text = str(assigned_to.get("displayName") or assigned_to.get("uniqueName") or "")
    else:
        assigned_to_text = str(assigned_to or "")

    lines = [
        f"Azure DevOps Work Item: {work_item_id}",
        f"Title: {title}" if title else "Title: (missing)",
        f"State: {state}" if state else "State: (missing)",
    ]
    if assigned_to_text:
        lines.append(f"Assigned To: {assigned_to_text}")
    if tag_text:
        lines.append(f"Tags: {tag_text}")
    if description:
        lines.append(f"Description: {description}")
    else:
        lines.append("Description: (missing)")
    if acceptance:
        lines.append(f"Acceptance Criteria: {acceptance}")
    else:
        lines.append("Acceptance Criteria: (missing)")

    return "\n".join(lines)


def _to_html(text: str) -> str:
    """ADO work-item fields render HTML — escape and keep line breaks."""
    return html.escape(text or "").replace("\n", "<br>")


def get_work_item_assignee(
    *, org_url: str, project: str, pat: str, work_item_id: str, timeout: int = 10
) -> str:
    """Return the uniqueName (email/UPN) the given work item is assigned to, or ''."""
    org_url = org_url.strip().rstrip("/")
    project = project.strip()
    pat = pat.strip()
    work_item_id = str(work_item_id).strip()
    if not (org_url and project and pat and work_item_id):
        return ""

    url = f"{org_url}/{project}/_apis/wit/workitems/{work_item_id}?api-version=7.1"
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url, headers={"Authorization": f"Basic {token}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:  # pragma: no cover - best-effort network helper
        return ""

    assigned = (payload.get("fields", {}) or {}).get("System.AssignedTo")
    if isinstance(assigned, dict):
        return str(assigned.get("uniqueName") or assigned.get("displayName") or "")
    return str(assigned or "")


def create_work_item(
    *,
    org_url: str,
    project: str,
    pat: str,
    title: str,
    description: str,
    work_item_type: str = "Bug",
    assigned_to: str = "",
    tags: str = "",
    parent_id: str = "",
    timeout: int = 15,
) -> str:
    """Create an ADO work item and return a human-readable result line.

    When parent_id is given the item is created as a CHILD (subtask) of that work
    item via a Hierarchy-Reverse link, so a regression failure attaches to the ticket
    that drove the change instead of spawning a standalone bug.

    Best-effort: returns a readable message on any failure instead of raising, so a
    CI failure-handler never masks the original test failure. If the assignee cannot
    be resolved by ADO, the item is created unassigned rather than failing outright.
    """
    parent_id = str(parent_id).strip()
    org_url = org_url.strip().rstrip("/")
    project = project.strip()
    pat = pat.strip()
    if not (org_url and project and pat):
        return "Skipped ADO ticket creation: AZDO_ORG_URL / AZDO_PROJECT / AZDO_PAT are not all set."

    import urllib.parse

    wit = urllib.parse.quote("$" + work_item_type)  # e.g. "$Bug" -> "%24Bug"
    url = f"{org_url}/{project}/_apis/wit/workitems/{wit}?api-version=7.1"
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
    html_desc = _to_html(description)

    def _patch(include_assignee: bool) -> bytes:
        ops = [
            {"op": "add", "path": "/fields/System.Title", "value": title[:255]},
            {"op": "add", "path": "/fields/System.Description", "value": html_desc},
        ]
        if work_item_type.lower() == "bug":
            ops.append({"op": "add", "path": "/fields/Microsoft.VSTS.TCM.ReproSteps", "value": html_desc})
        if tags:
            ops.append({"op": "add", "path": "/fields/System.Tags", "value": tags})
        if include_assignee and assigned_to:
            ops.append({"op": "add", "path": "/fields/System.AssignedTo", "value": assigned_to})
        if parent_id:
            ops.append({"op": "add", "path": "/relations/-", "value": {
                "rel": "System.LinkTypes.Hierarchy-Reverse",  # link new item AS A CHILD of parent
                "url": f"{org_url}/_apis/wit/workItems/{parent_id}",
            }})
        return json.dumps(ops).encode("utf-8")

    def _post(body: bytes) -> dict:
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/json-patch+json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        payload = _post(_patch(include_assignee=True))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:300]
        except Exception:
            pass
        # A bad/unknown assignee identity is the usual cause — retry unassigned.
        if assigned_to and exc.code in (400, 404):
            try:
                payload = _post(_patch(include_assignee=False))
                wid = payload.get("id")
                parent_note = f" as a subtask of #{parent_id}" if parent_id else ""
                return (f"Created ADO {work_item_type} {wid}{parent_note} (unassigned — could not "
                        f"resolve '{assigned_to}'): {_web_url(org_url, project, wid, payload)}")
            except Exception as exc2:  # pragma: no cover
                return f"Failed to create ADO work item: {exc2}"
        return f"Failed to create ADO work item: HTTP {exc.code} {detail}"
    except Exception as exc:  # pragma: no cover - best-effort network helper
        return f"Failed to create ADO work item: {exc}"

    wid = payload.get("id")
    assignee_note = f" assigned to {assigned_to}" if assigned_to else " (unassigned)"
    parent_note = f" as a subtask of #{parent_id}" if parent_id else ""
    return f"Created ADO {work_item_type} {wid}{parent_note}{assignee_note}: {_web_url(org_url, project, wid, payload)}"


def _web_url(org_url: str, project: str, wid, payload: dict) -> str:
    link = (((payload.get("_links") or {}).get("html") or {}).get("href"))
    return link or f"{org_url}/{project}/_workitems/edit/{wid}"


def _auth_header(pat: str) -> str:
    return "Basic " + base64.b64encode(f":{pat.strip()}".encode("utf-8")).decode("ascii")


def _api_get(url: str, pat: str, timeout: int = 10) -> dict:
    request = urllib.request.Request(
        url, headers={"Authorization": _auth_header(pat), "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# States that mean a subtask is finished — a new failure should open/append, not dedupe.
_CLOSED_STATES = {"closed", "done", "resolved", "removed", "completed"}


def find_open_regression_child(
    *, org_url: str, project: str, pat: str, parent_id: str,
    tag: str = "regression", timeout: int = 10,
) -> str:
    """Return the id of an OPEN regression subtask already linked under parent_id, or
    '' if none — so a repeated failure updates the existing subtask instead of piling
    on new ones. Best-effort: any API error returns '' (fall back to creating one)."""
    org_url = org_url.strip().rstrip("/")
    project = project.strip()
    pat = pat.strip()
    parent_id = str(parent_id).strip()
    if not (org_url and project and pat and parent_id):
        return ""

    try:
        parent = _api_get(
            f"{org_url}/{project}/_apis/wit/workitems/{parent_id}?$expand=relations&api-version=7.1",
            pat, timeout)
    except Exception:
        return ""

    child_ids = []
    for rel in parent.get("relations", []) or []:
        if rel.get("rel") == "System.LinkTypes.Hierarchy-Forward":  # Forward = children
            cid = (rel.get("url") or "").rstrip("/").split("/")[-1]
            if cid.isdigit():
                child_ids.append(cid)
    if not child_ids:
        return ""

    try:
        fields = "System.State,System.Tags,System.Title"
        batch = _api_get(
            f"{org_url}/{project}/_apis/wit/workitems?ids={','.join(child_ids[:200])}"
            f"&fields={fields}&api-version=7.1", pat, timeout)
    except Exception:
        return ""

    for wi in batch.get("value", []) or []:
        f = wi.get("fields", {}) or {}
        state = str(f.get("System.State", "")).lower()
        tags = str(f.get("System.Tags", "")).lower()
        title = str(f.get("System.Title", "")).lower()
        is_regression = tag.lower() in tags or "regression tests failing" in title
        if is_regression and state not in _CLOSED_STATES:
            return str(wi.get("id"))
    return ""


def add_comment(
    *, org_url: str, project: str, pat: str, work_item_id: str, text: str, timeout: int = 10,
) -> bool:
    """Append a discussion comment to a work item. Returns True on success."""
    org_url = org_url.strip().rstrip("/")
    project = project.strip()
    if not (org_url and project and pat and str(work_item_id).strip()):
        return False
    url = (f"{org_url}/{project}/_apis/wit/workItems/{work_item_id}/comments"
           "?api-version=7.1-preview.3")
    body = json.dumps({"text": text}).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": _auth_header(pat), "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
        return True
    except Exception:
        return False