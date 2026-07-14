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
import urllib.parse
import socket
import xml.etree.ElementTree as ET
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
            "head_sha": (r.get("head_sha") or "")[:7],
            "commit_msg": (((r.get("head_commit") or {}).get("message", "").splitlines() or [""])[0]),
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


def latest_pipeline(run_id=None):
    """A run flattened into an ordered step list, with the index of the step
    currently executing. Also returns the recent-run list so the UI can offer a
    picker (several workflows run at once). Pass run_id to inspect a specific run;
    otherwise the newest in-progress run (else the most recent) is chosen."""
    runs = list_runs(limit=15)
    if not runs:
        return {"run": None, "steps": [], "current": None, "runs": []}
    if run_id is not None:
        run = next((r for r in runs if r.get("id") == run_id), None)
        if run is None:  # older than the window — synthesize a minimal header
            run = {"id": run_id, "workflow": f"run {run_id}", "name": f"run {run_id}",
                   "status": None, "conclusion": None, "run_number": "", "branch": "",
                   "event": "", "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}"}
    else:
        run = next((r for r in runs if r.get("status") != "completed"), runs[0])
    steps = []
    for j in run_jobs(run["id"]):
        for s in j.get("steps", []):
            steps.append({
                "name": s.get("name"),
                "status": s.get("status"),          # queued | in_progress | completed
                "conclusion": s.get("conclusion"),  # success | failure | skipped | ...
                "started_at": s.get("started_at"),
                "completed_at": s.get("completed_at"),
            })
    current = next((i for i, s in enumerate(steps) if s.get("status") == "in_progress"), None)
    if current is None and run.get("status") != "completed":
        current = next((i for i, s in enumerate(steps) if s.get("status") != "completed"), None)
    return {"run": run, "steps": steps, "current": current, "runs": runs}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # don't auto-follow — we re-fetch unauthenticated
        return None


def _download_artifact(archive_url: str) -> bytes:
    """Download an artifact zip. GitHub 302-redirects artifact URLs to signed blob
    storage that REJECTS the Authorization header (that's the '401 www-authenticate'
    error) — so we capture the redirect and fetch the signed URL with no auth."""
    req = urllib.request.Request(archive_url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "testgen-dashboard",
    })
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=60) as resp:   # no redirect (rare) — direct bytes
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            loc = e.headers.get("Location")
            with urllib.request.urlopen(loc, timeout=60) as r:  # signed URL, unauthenticated
                return r.read()
        raise


def _find_artifact(run_id: int, *needles):
    arts = _gh(f"/repos/{REPO}/actions/runs/{run_id}/artifacts")
    for a in arts.get("artifacts", []):
        name = a["name"].lower()
        if any(n in name for n in needles):
            return a
    return None


def run_cucumber_artifact(run_id: int):
    """Download + parse the Java cucumber-report artifact for a run, if present."""
    target = _find_artifact(run_id, "cucumber-report-java", "cucumber")
    if not target:
        return None
    zipped = _download_artifact(target["archive_download_url"])
    with zipfile.ZipFile(io.BytesIO(zipped)) as zf:
        name = next((n for n in zf.namelist() if n.endswith(".json")), None)
        if not name:
            return None
        return json.loads(zf.read(name))


def run_dotnet_trx(run_id: int):
    """Download the .NET TRX artifact for a run and return its raw XML bytes, if present."""
    target = _find_artifact(run_id, "dotnet-test-results", "trx")
    if not target:
        return None
    zipped = _download_artifact(target["archive_download_url"])
    with zipfile.ZipFile(io.BytesIO(zipped)) as zf:
        name = next((n for n in zf.namelist() if n.endswith(".trx")), None)
        if not name:
            return None
        return zf.read(name)


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
        features.append({"name": feature.get("name"), "scenarios": scenarios, "lang": "java"})

    return {"features": features, "totals": totals,
            "total": sum(totals.values())}


_TRX_NS = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}


def _trx_ms(dur: str) -> float:
    """TRX duration 'HH:MM:SS.fffffff' → milliseconds."""
    if not dur:
        return 0.0
    try:
        h, m, s = dur.split(":")
        return round((int(h) * 3600 + int(m) * 60 + float(s)) * 1000, 1)
    except Exception:
        return 0.0


def _split_trx_name(name: str):
    """Turn a SpecFlow test name into (feature, scenario) for display."""
    name = name or ""
    if "." in name:
        parts = name.split(".")
        feat = parts[-2] if len(parts) >= 2 else "SpecFlow"
        scen = parts[-1]
    else:
        feat, scen = "SpecFlow", name
    feat = feat.replace("Feature", "").strip() or "SpecFlow"
    return feat, scen


def parse_trx(data: bytes) -> dict:
    """Flatten a .NET TRX report into the same per-feature/scenario shape as the
    Cucumber parser, so Java and .NET results render identically."""
    totals = {"passed": 0, "failed": 0, "skipped": 0}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {"features": [], "totals": totals, "total": 0}

    by_feature = {}
    for utr in root.findall(".//t:UnitTestResult", _TRX_NS):
        outcome = (utr.get("outcome") or "").lower()
        status = "passed" if outcome == "passed" else "failed" if outcome == "failed" else "skipped"
        totals[status] = totals.get(status, 0) + 1
        msg_el = utr.find(".//t:Message", _TRX_NS)
        err = (msg_el.text or "").strip() if msg_el is not None else ""
        feat, scen = _split_trx_name(utr.get("testName") or "")
        by_feature.setdefault(feat, []).append({
            "name": scen,
            "status": status,
            "duration_ms": _trx_ms(utr.get("duration") or ""),
            "failed_step": (err.splitlines()[0][:120] if (status == "failed" and err) else None),
            "error": err,
        })
    features = [{"name": f, "scenarios": s, "lang": "dotnet"} for f, s in by_feature.items()]
    return {"features": features, "totals": totals, "total": sum(totals.values())}


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

        if path == "/api/pipeline":
            qs = urllib.parse.parse_qs(self.path.partition("?")[2])
            rid = qs.get("run", [None])[0]
            run_id = int(rid) if rid and rid.isdigit() else None
            return self._json_safe(lambda: latest_pipeline(run_id))

        if path.startswith("/api/runs/") and path.endswith("/jobs"):
            run_id = int(path.split("/")[3])
            return self._json_safe(lambda: run_jobs(run_id))

        if path.startswith("/api/runs/") and path.endswith("/results"):
            run_id = int(path.split("/")[3])

            def fetch():
                parts = []  # (source-label, parsed-result) for whichever suites ran
                java_report = run_cucumber_artifact(run_id)
                if java_report is not None:
                    parts.append(("Java", parse_cucumber(java_report)))
                trx = run_dotnet_trx(run_id)
                if trx is not None:
                    parts.append((".NET", parse_trx(trx)))

                if not parts:
                    out = local_results()
                    out["source"] = "local fallback (no test artifacts on this run)"
                    return out

                features, totals, srcs = [], {"passed": 0, "failed": 0, "skipped": 0}, []
                for label, res in parts:
                    features += res.get("features", [])
                    for k, v in res.get("totals", {}).items():
                        totals[k] = totals.get(k, 0) + v
                    srcs.append(f"{label} artifact")
                return {"features": features, "totals": totals,
                        "total": sum(totals.values()), "source": " + ".join(srcs)}
            return self._json_safe(fetch)

        if path == "/api/results":  # local report, always available
            out = local_results()
            out["source"] = "local cucumber-report.json"
            return self._send(200, out)

        return self._send(404, {"error": "not found"})


class Server(ThreadingHTTPServer):
    allow_reuse_address = True  # reclaim a port left in TIME_WAIT by a prior run


def _serve(port: int) -> Server:
    """Bind to `port`, or the next few ports if it's busy (e.g. a stray prior
    instance is still holding it) — so the demo never dies on 'Address in use'."""
    last = None
    for candidate in range(port, port + 10):
        try:
            return Server(("0.0.0.0", candidate), Handler)
        except OSError as e:
            last = e
            if candidate == port:
                print(f"Port {port} is in use, trying {candidate + 1}…")
    raise last


def main():
    httpd = _serve(PORT)
    actual = httpd.server_address[1]
    print(f"Dashboard → http://localhost:{actual}", flush=True)
    print(f"Repo: {REPO}   GitHub token: {'set' if TOKEN else 'NOT set (panes will prompt)'}", flush=True)
    print(f"Local report: {'found' if LOCAL_REPORT.is_file() else 'missing (run mvn verify)'}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
