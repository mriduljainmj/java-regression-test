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