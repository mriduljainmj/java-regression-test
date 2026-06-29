"""Azure DevOps (ADO) integration — pull the work-item description, acceptance
criteria, and reviewer comments to feed the generator as *intent*.

The git diff tells the agent WHAT changed; the ticket tells it WHY and what
"correct" looks like (acceptance criteria, expected values, edge cases the
reviewer cares about). Supplying both makes the model pick the right boundary
values and surfaces code/spec mismatches instead of blessing them.

Stdlib only (urllib). Auth is a Personal Access Token via HTTP Basic. Everything
degrades gracefully: if ADO isn't configured or a call fails, the agent runs
exactly as before with empty ticket context.

Configuration (env):
    ADO_ORG        organization (e.g. "contoso")            — required to fetch
    AZURE_DEVOPS_PAT / ADO_PAT   personal access token       — required to fetch
    ADO_PROJECT    project name/id (optional for get-by-id)
    ADO_BASE_URL   override for Azure DevOps Server/on-prem  (default https://dev.azure.com)
"""

import base64
import html
import json
import logging
import os
import re
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# Azure Boards mention syntax (AB#123) and bare #123 in commit messages / PRs.
_WORK_ITEM_RE = re.compile(r"(?:AB#|#)(\d+)", re.IGNORECASE)

_API_VERSION = "7.0"


def extract_work_item_ids(text: str) -> list:
    """Find work-item ids referenced in commit messages / PR text (AB#123, #123)."""
    seen = []
    for m in _WORK_ITEM_RE.finditer(text or ""):
        wid = m.group(1)
        if wid not in seen:
            seen.append(wid)
    return seen


def html_to_text(value) -> str:
    """ADO description/criteria/comments are HTML. Reduce to readable plain text."""
    if not value:
        return ""
    s = str(value)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "- ", s)
    s = re.sub(r"<[^>]+>", "", s)          # strip remaining tags
    s = html.unescape(s)                   # &amp; &nbsp; etc.
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _config():
    org = os.environ.get("ADO_ORG")
    pat = os.environ.get("AZURE_DEVOPS_PAT") or os.environ.get("ADO_PAT")
    project = os.environ.get("ADO_PROJECT")
    base = os.environ.get("ADO_BASE_URL", "https://dev.azure.com").rstrip("/")
    return org, project, pat, base


def is_configured() -> bool:
    org, _project, pat, _base = _config()
    return bool(org and pat)


def _get(url: str, pat: str) -> dict:
    token = base64.b64encode(f":{pat}".encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "User-Agent": "testgen-agent",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _parse_work_item(payload: dict) -> dict:
    """Pull the fields we care about out of a work-item API response."""
    fields = payload.get("fields", {})
    return {
        "id": payload.get("id"),
        "type": fields.get("System.WorkItemType", ""),
        "title": fields.get("System.Title", ""),
        "state": fields.get("System.State", ""),
        "description": html_to_text(fields.get("System.Description", "")),
        "acceptance_criteria": html_to_text(
            fields.get("Microsoft.VSTS.Common.AcceptanceCriteria", "")
        ),
    }


def _parse_comments(payload: dict) -> list:
    """Pull comment author + text out of the comments API response."""
    out = []
    for c in payload.get("comments", []):
        author = (c.get("createdBy") or {}).get("displayName", "someone")
        text = html_to_text(c.get("text", ""))
        if text:
            out.append(f"{author}: {text}")
    return out


def fetch_work_item(work_item_id, include_comments: bool = True) -> dict:
    """Fetch a work item (and optionally its comments). Returns {} if ADO isn't
    configured or the call fails — never raises into the pipeline."""
    org, project, pat, base = _config()
    if not (org and pat):
        return {}

    scope = f"{base}/{org}/{project}" if project else f"{base}/{org}"
    try:
        wi = _parse_work_item(
            _get(f"{scope}/_apis/wit/workitems/{work_item_id}?api-version={_API_VERSION}", pat)
        )
    except urllib.error.HTTPError as e:
        logger.warning("ADO work item %s fetch failed: %s %s", work_item_id, e.code, e.reason)
        return {}
    except Exception as e:  # network/JSON/etc — non-fatal
        logger.warning("ADO work item %s fetch failed: %s", work_item_id, e)
        return {}

    if include_comments:
        try:
            wi["comments"] = _parse_comments(
                _get(f"{scope}/_apis/wit/workItems/{work_item_id}/comments"
                     f"?api-version={_API_VERSION}-preview.3", pat)
            )
        except Exception as e:
            logger.warning("ADO comments for %s unavailable: %s", work_item_id, e)
            wi["comments"] = []
    return wi


def format_ticket_context(work_items: list) -> str:
    """Render fetched work items into the prompt's TICKET section."""
    if not work_items:
        return "Not provided."
    blocks = []
    for wi in work_items:
        if not wi:
            continue
        parts = [f"Work item #{wi.get('id')} [{wi.get('type')}] — {wi.get('title')}"]
        if wi.get("state"):
            parts.append(f"State: {wi['state']}")
        if wi.get("description"):
            parts.append(f"Description:\n{wi['description']}")
        if wi.get("acceptance_criteria"):
            parts.append(f"Acceptance criteria:\n{wi['acceptance_criteria']}")
        blocks.append("\n".join(parts))
    return "\n\n---\n\n".join(blocks) if blocks else "Not provided."


def collect_reviewer_comments(work_items: list) -> list:
    """Flatten work-item comments to use as reviewer guidance."""
    comments = []
    for wi in work_items:
        comments.extend(wi.get("comments", []) if wi else [])
    return comments
