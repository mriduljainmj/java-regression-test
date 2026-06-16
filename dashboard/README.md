# Pipeline Dashboard

A single-screen view that merges the two halves of the pipeline:

- **Left** — GitHub Actions runs → jobs → steps, with live status and timing.
- **Right** — Cucumber scenarios, grouped by feature, green/red with durations
  and the failing step when one fails.

Stdlib-only Python backend (no `pip install`) + one self-contained HTML page.
Auto-refreshes every 5 seconds.

## Run it

```bash
# optional — without it, the left pane prompts for a token; the right pane
# still works from the local report
export GITHUB_TOKEN=ghp_...        # a PAT with actions:read (repo scope)

python3 dashboard/server.py        # → http://localhost:8000
```

The **test pane works with zero setup** as long as a local report exists — run
`mvn -f java-component/pom.xml verify` once and it reads
`java-component/target/cucumber-report.json`. This is the safe default for a
live demo: even with no network or token, the right side shows all scenarios.

With `GITHUB_TOKEN` set, the left pane lists recent workflow runs; click one to
expand its jobs/steps **and** load that run's Cucumber results (downloaded from
the run's artifact) into the right pane.

## How it works

```
browser (index.html, polls every 5s)
        │
        ▼
server.py  ──/api/runs──────────▶ GitHub Actions API (runs)
           ──/api/runs/{id}/jobs▶ GitHub Actions API (jobs + steps)
           ──/api/runs/{id}/results─▶ download cucumber artifact → parse
           ──/api/results──────────▶ local cucumber-report.json (fallback)
```

`parse_cucumber()` flattens the report: a scenario is **passed** only if every
step (including background steps) passed; durations (nanoseconds in the report)
are summed and shown in ms.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | — | PAT with `actions:read`; enables the pipeline pane |
| `GH_REPO` | `mriduljainmj/java-regression-test` | which repo to read |
| `PORT` | `8000` | server port |

## Demo script (≈2 min)

1. `mvn -f java-component/pom.xml verify` → generates the local report.
2. `python3 dashboard/server.py`, open http://localhost:8000.
3. **Right pane**: "29 scenarios across 3 features, all green — this is the
   regression suite the agent maintains." Point out a feature, a scenario,
   the per-scenario duration.
4. **Left pane** (with token): "Same screen shows the CI pipeline — here's the
   generate-tests run that opened the PR, expand it to see each step." Click a
   run; its artifact results load on the right.
5. Tie it together: code change → generate-tests run (left) → PR → regression
   run (left) → scenarios (right).

## Limits (it's a demo tool, not production)

- Polls on a fixed 5s timer; no websockets.
- No auth on the dashboard itself — run it locally, don't expose the port.
- GitHub free API rate limit is 5,000 req/hour authenticated; the 5s poll over
  a few expanded runs stays well under it.
