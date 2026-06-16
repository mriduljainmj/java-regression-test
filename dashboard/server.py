"""Test-gen pipeline dashboard — stdlib-only backend.

Serves a single-page UI plus a small JSON API that merges two data streams:

  1. GitHub Actions  — workflow runs -> jobs -> steps (live, via the REST API)
  2. Cucumber report — per-scenario pass/fail (from the run's artifact, or the
                        local target/cucumber-report.json as a fallback)

Run:
    export GITHUB_TOKEN=ghp_...        # optional; without it, GitHub panes are empty
    python3 dashboard/server.py        # then open http://localhost:8000

No third-party dependencies — only the Python standard library.

Environment:
    GITHUB_TOKEN   PAT with `actions:read` (repo scope on a classic token).
    GH_REPO        owner/repo  (default: mriduljainmj/java-regression-test)
    PORT           default 8000
"""

import json
import os
import io
import zipfile
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = os.environ.get("GH_REPO", "mriduljainmj/java-regression-test")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
PORT = int(os.environ.get("PORT", "8000"))

ROOT = Path(__file__).resolve().parent
# Local Cucumber report, used as a fallback so the test pane is never empty.
LOCAL_REPORT = ROOT.parent / "java-component" / "target" / "cucumber-report.json"

API = "https://api.github.com"


# --------------------------------------------------------------------------- #
# GitHub REST helpers
# --------------------------------------------------------------------------- #
def _gh(path: str, raw: bool = False):
    """GET a GitHub API path. Returns parsed JSON, or raw bytes when raw=True."""
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN not set")
    url = path if path.startswith("http") else f"{API}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "testgen-dashboard",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    return data if raw else json.loads(data)


def list_runs(limit: int = 20):
    """Recent workflow runs across all workflows, newest first."""
    data = _gh(f"/repos/{REPO}/actions/runs?per_page={limit}")
    runs = []
    for r in data.get("workflow_runs", []):
        runs.append({
            "id": r["id"],
            "name": r.get("name") or r.get("display_title"),
            "workflow": r.get("name"),
            "branch": r.get("head_branch"),
            "event": r.get("event"),
            "status": r.get("status"),          # queued | in_progress | completed
            "conclusion": r.get("conclusion"),  # success | failure | ...
            "run_number": r.get("run_number"),
            "created_at": r.get("created_at"),
            "html_url": r.get("html_url"),
            "commit": (r.get("head_commit") or {}).get("message", "").splitlines()[:1],
        })
    return runs


def run_jobs(run_id: int):
    """Jobs and their steps for a run — the pipeline step tree."""
    data = _gh(f"/repos/{REPO}/actions/runs/{run_id}/jobs")
    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "id": j["id"],
            "name": j["name"],
            "status": j.get("status"),
            "conclusion": j.get("conclusion"),
            "started_at": j.get("started_at"),
            "completed_at": j.get("completed_at"),
            "steps": [{
                "number": s.get("number"),
                "name": s.get("name"),
                "status": s.get("status"),
                "conclusion": s.get("conclusion"),
                "started_at": s.get("started_at"),
                "completed_at": s.get("completed_at"),
            } for s in j.get("steps", [])],
        })
    return jobs


def run_cucumber_artifact(run_id: int):
    """Download + parse the cucumber-report artifact for a run, if present."""
    arts = _gh(f"/repos/{REPO}/actions/runs/{run_id}/artifacts")
    target = next((a for a in arts.get("artifacts", [])
                   if "cucumber" in a["name"].lower()), None)
    if not target:
        return None
    zipped = _gh(target["archive_download_url"], raw=True)
    with zipfile.ZipFile(io.BytesIO(zipped)) as zf:
        name = next((n for n in zf.namelist() if n.endswith(".json")), None)
        if not name:
            return None
        return json.loads(zf.read(name))


# --------------------------------------------------------------------------- #
# Cucumber report parsing
# --------------------------------------------------------------------------- #
def parse_cucumber(report: list) -> dict:
    """Flatten a Cucumber JSON report into per-feature, per-scenario results.

    A scenario passes only if every step (including its background steps)
    passed. Durations are nanoseconds in the report; summed and exposed as ms.
    """
    features = []
    totals = {"passed": 0, "failed": 0, "skipped": 0}

    for feature in report:
        scenarios = []
        background_steps = []  # carried into each following scenario
        for el in feature.get("elements", []):
            steps = el.get("steps", [])
            if el.get("type") == "background":
                background_steps = steps
                continue

            all_steps = background_steps + steps
            statuses = [s.get("result", {}).get("status", "skipped") for s in all_steps]
            if any(st in ("failed", "undefined", "pending", "ambiguous") for st in statuses):
                status = "failed"
            elif statuses and all(st == "passed" for st in statuses):
                status = "passed"
            else:
                status = "skipped"
            totals[status] = totals.get(status, 0) + 1

            duration_ns = sum(s.get("result", {}).get("duration", 0) for s in all_steps)
            failed_step = next(
                (s["name"] for s in all_steps
                 if s.get("result", {}).get("status") in
                 ("failed", "undefined", "pending", "ambiguous")),
                None,
            )
            scenarios.append({
                "name": el.get("name"),
                "status": status,
                "duration_ms": round(duration_ns / 1_000_000, 1),
                "steps": len(all_steps),
                "failed_step": failed_step,
                "error": next((s.get("result", {}).get("error_message", "")
                               for s in all_steps
                               if s.get("result", {}).get("status") == "failed"), ""),
            })
        features.append({"name": feature.get("name"), "scenarios": scenarios})

    return {"features": features, "totals": totals,
            "total": sum(totals.values())}


def local_results():
    if LOCAL_REPORT.is_file():
        return parse_cucumber(json.loads(LOCAL_REPORT.read_text()))
    return {"features": [], "totals": {"passed": 0, "failed": 0, "skipped": 0},
            "total": 0, "note": "no local cucumber-report.json (run mvn verify)"}


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet console during the demo
        pass

    def _send(self, code, body, content_type="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_safe(self, fn):
        """Run a GitHub call, turning auth/network errors into a clean JSON
        payload the UI can render instead of a 500."""
        try:
            return self._send(200, fn())
        except RuntimeError as e:       # no token
            return self._send(200, {"error": str(e), "needs_token": True})
        except urllib.error.HTTPError as e:
            return self._send(200, {"error": f"GitHub API {e.code}: {e.reason}"})
        except Exception as e:
            return self._send(200, {"error": str(e)})

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            return self._send(200, (ROOT / "index.html").read_text(), "text/html")

        if path == "/api/config":
            return self._send(200, {"repo": REPO, "has_token": bool(TOKEN)})

        if path == "/api/runs":
            return self._json_safe(list_runs)

        if path.startswith("/api/runs/") and path.endswith("/jobs"):
            run_id = int(path.split("/")[3])
            return self._json_safe(lambda: run_jobs(run_id))

        if path.startswith("/api/runs/") and path.endswith("/results"):
            run_id = int(path.split("/")[3])

            def fetch():
                report = run_cucumber_artifact(run_id)
                if report is None:
                    out = local_results()
                    out["source"] = "local fallback (no artifact on this run)"
                    return out
                out = parse_cucumber(report)
                out["source"] = "github artifact"
                return out
            return self._json_safe(fetch)

        if path == "/api/results":  # local report, always available
            out = local_results()
            out["source"] = "local cucumber-report.json"
            return self._send(200, out)

        return self._send(404, {"error": "not found"})


def main():
    print(f"Dashboard → http://localhost:{PORT}")
    print(f"Repo: {REPO}   GitHub token: {'set' if TOKEN else 'NOT set (panes will prompt)'}")
    print(f"Local report: {'found' if LOCAL_REPORT.is_file() else 'missing (run mvn verify)'}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
