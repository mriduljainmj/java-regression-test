# javaTest — AI regression test generation pipeline

An agent (`testgen-agent/`, Python + LangGraph) that reads a git diff, generates
BDD regression tests, runs them, self-corrects on failure, and opens a PR for
human review. Supports three independent lanes — Java (Cucumber/RestAssured),
.NET (SpecFlow/HttpClient), and any JS-rendered frontend (Cucumber-JS +
Playwright) — plus a dashboard, Azure DevOps integration, and a PROJECT.md
mind-map of the system.

## Repo layout

| Path | What it is |
|---|---|
| `testgen-agent/` | The agent itself — portable, this is what you'd copy into a real repo |
| `java-component/` | Demo fixture: Spring Boot app + Cucumber tests (Java lane's target) |
| `dotnet-component/` | Demo fixture: ASP.NET Core app + SpecFlow tests (.NET lane's target) |
| `frontend-react/` | Demo fixture: React app + Cucumber-JS/Playwright tests (UI lane's target) |
| `.github/workflows/` | The 5 CI workflows driving the pipeline (see below) |
| `PROJECT.md` | QA-owned mind-map: per-controller criticality (LOW/MEDIUM/HIGH), skip list |

**`java-component`/`dotnet-component`/`frontend-react` are demo fixtures, not
part of the portable agent.** When integrating this into a real project, copy
`testgen-agent/` + the workflows and point them at the real code via the env
vars below — don't paste the fixture apps into a real repo too.

## Agent architecture (`testgen-agent/testgen/`)

LangGraph state machine (`graph.py`):
```
collect_diff → gather_context → generate_tests → validate_output
                                      ▲   ▲              │
                        (struct. errs,┘   │              │ (clean)
                         retries left)    │              ▼
                                          │        write_features → run_generated_tests
                     (tests failed, ─────┘                              │
                      retries left)                     (pass, or out of retries)
                                                                        ▼
                                                              create_pull_request
```
- `collect_diff` detects `project_type` ∈ `java | dotnet | ui` from the diff's
  file extensions/paths (priority `dotnet > java > ui` when a single run is
  forced to pick one — see the CI note below for why that priority rarely
  matters anymore). `TESTGEN_FORCE_PROJECT_TYPE` overrides detection.
- `nodes.py` holds all three lanes' logic; `prompts.py` / `dotnet_prompt.py` /
  `ui_prompt.py` are the per-lane system/user prompts; `gherkin.py` parses
  cucumber-expression step definitions (Java/C# `@Given(...)`/`[Given(...)]`
  and JS `Given(...)`) to catch undefined-step mismatches before they reach CI.
- Model calls go through **OpenRouter** (`OpenAI` client, `base_url=
  https://openrouter.ai/api/v1`), not the Anthropic API directly — model
  strings need the OpenRouter slug format (`anthropic/...`, `openai/...`),
  verify the exact slug on openrouter.ai/models before setting `TESTGEN_MODEL`.
- Free OpenRouter models are unstable (rate limits, occasional removal) and
  not always capable enough for the harder cases (computed-numeric assertions,
  UI selector reasoning). A funded model is recommended for real use.

## Portability — env vars (this is the interesting part)

Every path is derived from one overridable component-dir var per lane, not a
hardcoded literal — verified in `tests/test_portability.py`.

| Lane | Component dir | Extra overrides |
|---|---|---|
| Java | `TESTGEN_COMPONENT_DIR` (default `java-component`) | `TESTGEN_JAVA_SOURCE_MARKER`, `TESTGEN_JAVA_TEST_MARKER`, `TESTGEN_JAVA_FEATURES_DIR` |
| .NET | `TESTGEN_DOTNET_COMPONENT_DIR` (default `dotnet-component`) | `TESTGEN_DOTNET_TEST_PROJECT` (default `BP.Tests.csproj`), `TESTGEN_DOTNET_FEATURES_DIR`, `TESTGEN_DOTNET_TESTS_DIR` |
| UI | `TESTGEN_UI_COMPONENT_DIR` (default `frontend-react`) | `TESTGEN_UI_SOURCE_MARKER`, `TESTGEN_UI_TESTS_DIR`, `TESTGEN_UI_FEATURES_DIR` |

These are read **once at module import** (`os.environ.get(...)` at the top of
`nodes.py`) — set them before the process starts, not mid-run. In CI they're
sourced from GitHub repo Variables (Settings → Actions → Variables) with the
same names, defaulting to this demo's layout.

**One thing that can't be made dynamic:** GitHub evaluates a workflow's
trigger-level `on.push.paths` before any run exists, so those specific lines
can't reference `vars.*`. When copying a workflow into a new repo, hand-edit
the folder-scoped trigger entries (each is commented where it appears);
extension-based entries (`**/*.cs`, `**/*.jsx`, …) already work regardless of
folder name. Java's trigger in particular was fixed to `**/*.java` (was
folder-scoped to `java-component/src/main/**`, which meant a Java service in
any other folder would never fire the workflow at all).

## CI workflows (`.github/workflows/`)

- **`generate-tests.yml`** — Step 1. Fires on push (or `workflow_dispatch`).
  Processes **every** project type detected in the diff independently, not
  just the highest-priority match — a mixed commit (e.g. backend + UI in one
  push) gets both processed, each with its own base, its own PR, its own tag.
  Tracks "last successfully processed commit" **per type** with a git tag
  (`testgen-verified/<branch>-<type>`), advanced only on success (including a
  clean skip or a PR opened with failing-but-generated tests — only an actual
  exception withholds it). A failed type's tag stays put, so the next push's
  diff for that type naturally accumulates instead of silently dropping the
  change. One type failing never blocks another type's tag from advancing.
- **`regression.yml`** — Step 2. Runs after a reviewed test PR merges: `mvn
  verify` and/or `dotnet test` for whichever component changed, gated by
  `PROJECT.md`'s criticality skip list, logs an ADO subtask on failure.
- **`ui-regression.yml`** — same idea as `regression.yml` but for the UI lane
  (Playwright + Cucumber-JS via `npm test`).
- **`refine-tests.yml`** — QA leaves a PR comment + adds the `regen-tests`
  label → rereads the comment as guidance, regenerates onto the same PR
  branch, removes the label.
- **`auto-update-mindmap.yml`** — keeps `PROJECT.md`'s controller/criticality
  mind-map in sync; `update-project-mindmap.py` does a repo-wide scan, no
  hardcoded folder names, needs no configuration.

**If you ever need to reseed the tracking tags** (e.g. after restructuring the
scheme), they live at `refs/tags/testgen-verified/<branch>-<type>` — don't
delete/rename them casually, that's how diff-loss-on-failure protection works.

## Known gotchas (hit these once already — don't rediscover them)

- **Cucumber.js ESM config must NOT wrap in `default: {...}`.** cucumber-js
  loads a `.mjs` config via `await import()` and uses the module namespace
  directly — the `export default {...}` object **is** the profile already.
  Wrapping it in another `{ default: {...} }` nests everything one level too
  deep and silently produces **0 scenarios found**, no error. (Found in
  `frontend-react/cucumber.mjs`.)
- **`generate-tests.yml`'s per-type bash blocks run with `working-directory:
  testgen-agent`** — any path referencing the repo root (e.g. the UI's `npm
  install`) must use `$GITHUB_WORKSPACE`, not a bare relative path.
- **This is explicitly NOT built for multiple microservices of the same
  language** (e.g. two separate Java services). The supported shape is one
  backend (Java *or* .NET) optionally paired with one UI. A single commit
  touching both a backend and the UI is handled correctly (see
  `generate-tests.yml` above); two backends of the same language sharing one
  repo is not — would need per-project discovery (nearest `pom.xml`/`*.csproj`
  ancestor), which hasn't been built.
- **Test-run screenshots/logs**: the UI suite (`frontend-react`)
  logs every step via a shared `log.step(...)` helper and capture a full-page
  Playwright screenshot to `reports/screenshots/` on any failed scenario
  (attached inline to the Cucumber HTML report too). `HEADLESS=false` (+
  optional `SLOWMO=<ms>`) opens a real visible browser for `npm test`.

## Running the agent's own tests

```bash
cd testgen-agent && python -m pytest -q
```
58 tests as of this writing (`tests/test_portability.py` is the one to check
first if a path/config change might have broken relocation). Keep this green.
