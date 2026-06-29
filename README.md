# AI-Generated BDD Regression Tests (Java + .NET)

A pipeline that keeps a Gherkin/BDD regression suite in sync with a REST component.
When the component's code changes, a Python LangGraph agent analyzes the git diff with
an LLM (via OpenRouter), generates/updates `.feature` files — and, when needed, new
step definitions — then opens a PR. After manual review and merge, the regression
suite runs in CI against the new code.

**Two languages, one agent.** The agent detects the component's language from the
changed files and adapts every language-specific step:

| | Java component | .NET component |
|---|---|---|
| Stack | Spring Boot, Cucumber + JUnit | ASP.NET Core, Reqnroll/SpecFlow + xUnit |
| Glue | Java `@Given("…")` cucumber expressions | C# `[Given(@"…")]` regex attributes |
| Test command | `mvn test` | `dotnet test` |
| Failures read from | `cucumber-report.json` | `dotnet test` console output |

The `.feature`/Gherkin files are identical across both — only the glue language,
build command, and failure format differ, all encapsulated in a `LanguageProfile`
(`testgen-agent/testgen/languages.py`). Adding a third stack means adding one profile.

## Flow

```
developer changes component code  (Java or .NET)
        │  push to main → paths: java-component/src/main/** | dotnet-component/Api/**
        ▼
[generate-tests.yml]  →  LangGraph agent:
        │   collect_diff      detect language (java | dotnet) from changed files
        │   gather_context    source + existing glue + features (+ API spec)
        │   generate_tests    LLM writes Gherkin + glue, in the detected language
        │        ▲            (delimited block format; model rotation on retries)
        │        │
        │   validate_output   step matching, every Examples row, paths, no dropped glue
        │        │  (structural errors → back to generate, retry budget)
        │        ▼
        │   write_features    write the files to disk
        │        │
        │   run_generated_tests   run `mvn test` / `dotnet test`
        │        │            FAIL → parse compile errors + scenario failures
        │        └──────────  → feed back to generate_tests (up to 3 self-corrections)
        │        ▼ pass (or out of retries)
        │   create_pull_request
        ▼
PR with new/updated tests  ──▶  regression check runs ON the PR
        │                       (defence in depth — catches anything the loop missed)
        ▼
manual review  ──▶  merge
        ▼
[regression.yml]  →  mvn verify / dotnet test on main  →  code and suite in sync
```

The agent doesn't just write tests — it **runs them and fixes itself**. Generated
tests that don't compile or assert the wrong value are caught by `run_generated_tests`
and corrected before the PR is opened (up to 3 rounds); only failures that survive
all rounds reach the PR, flagged as failing.

## Repository layout

| Path | What it is |
|---|---|
| `java-component/` | Java component under test: Spring Boot REST API with products (CRUD + price filtering + update/delete guards), orders (tiered bulk discounts, total cap), and reviews (rating bounds, average summary) — bean validation + `@RestControllerAdvice` |
| `dotnet-component/` | .NET counterpart: ASP.NET Core products API + Reqnroll/xUnit suite. Exists so language detection has a `dotnet` target (see its README; needs `dotnet test` to verify) |
| `<component>/.../features/` | The Gherkin regression suite (what the agent maintains) |
| `<component>/.../StepDefinitions` (Java `cucumber/`, C# `StepDefinitions/`) | Test harness: shared scenario state (`TestContext` bean / `TestState`), step-definition classes, framework wiring |
| `testgen-agent/` | Python LangGraph agent that generates the tests |
| `testgen-agent/testgen/languages.py` | `LanguageProfile`s + `detect_language` — the one place language-specific behavior lives |
| `dashboard/` | Stdlib dashboard merging GitHub Actions steps + per-scenario results into one UI |
| `demo/` | Staged one-command change scripts + runbook for live walkthroughs |
| `.github/workflows/generate-tests.yml` | Runs the agent when a component's source changes (or manually); opens the test PR |
| `.github/workflows/regression.yml` | Runs the right suite (`mvn verify` / `dotnet test`) per changed component, on pushes to `main` and PRs |

## When does each workflow run?

| Event | generate-tests | regression |
|---|---|---|
| Push to `main` touching a component's **source** (`java-component/src/main/**` or `dotnet-component/Api/**`) | ✅ (skipped for `test:` commits) | ✅ |
| Push to `main` touching only that component's tests/features | ❌ | ✅ |
| Any PR touching a component (incl. the agent's own PRs) | ❌ | ✅ — the pre-merge safety net |
| Push touching only `testgen-agent/`, `dashboard/`, `demo/`, workflows, docs | ❌ | ❌ |
| Manual (Actions → Run workflow, optional `base` input) | ✅ | ❌ |

`regression.yml` runs only the suite for the component that changed (a `dorny/paths-filter`
gate), so a Java-only change doesn't spin up the .NET job and vice versa.

## The agent (testgen-agent/)

LangGraph state machine:

`collect_diff → fetch_ticket_context → gather_context → generate_tests → validate_output → write_features → run_generated_tests → create_pull_request`

- **collect_diff** — `git diff base..head`; **detects the language** (java | dotnet)
  from the changed files and exits early if no main-source changed. Captures the
  commit messages in range (for work-item auto-detection). Handles CI edge cases:
  all-zero `before` SHA (first push), force-pushed/unreachable base (falls back to
  `head~1`, then the empty tree for single-commit repos).
- **fetch_ticket_context** — pulls **intent** to guide generation: the Azure DevOps
  work item's description + acceptance criteria + comments (via the ADO REST API),
  plus any direct reviewer guidance. Work-item ids come from `--work-item` or are
  auto-detected from the commit messages (`AB#123`). The ticket says what "correct"
  should be (so the model picks the right boundary values and coverage); reviewer
  guidance is treated as authoritative. No-ops gracefully when ADO isn't configured.
- **gather_context** — reads the full component source (changed files first), the
  glue code (found by step annotations/attributes, not file naming), every existing
  `.feature` file, and an OpenAPI spec if present. Skips `target/`, `bin/`, venvs, etc.
- **generate_tests** — prepends a `[LANGUAGE CONTEXT]` block (from the detected
  profile) telling the model the glue language, framework, and conventions, then
  calls the model via OpenRouter with a fallback chain + backoff on 429s. Output is
  a **delimited block format** (raw file contents between
  `=== FEATURE|STEPDEF CREATE|UPDATE <path> === … === END ===` markers) — free
  models reliably fail to JSON-escape source code, so JSON is only a tolerated
  fallback (with lone-backslash repair). Unparseable output re-enters the retry
  loop as feedback. Validation retries start from a **different model** in the chain.
- **validate_output** — structural Gherkin checks (Feature/Scenario present, Outline
  has Examples, paths under the test tree, no dropped existing glue, duplicates)
  **plus step-definition matching**: every generated step must match a step
  expression parsed from the glue — existing or proposed in the same generation —
  using the profile's matching style (Java cucumber expressions, C# regex
  attributes). Scenario Outline steps are checked with **every** Examples row
  substituted (catches `null` in an `{int}` column). Exact offending steps are fed
  back, up to `TESTGEN_MAX_ATTEMPTS` (default 6) generations.
- **write_features** — writes the files (skipping content-identical ones).
- **run_generated_tests** — runs the project's test command (`mvn test` for Java,
  `dotnet test` for .NET). On failure it parses **both** compile errors and
  per-scenario failures (feature → scenario → failing step → assertion message; from
  the Cucumber JSON report for Java, from `dotnet test` console for .NET) and feeds
  them back to `generate_tests`, looping up to `TESTGEN_MAX_TEST_ATTEMPTS` (default 3)
  times. This is the execution-feedback loop: it catches the *semantic* errors static
  validation can't — a wrong expected value, a miscomputed total, glue that doesn't
  compile. Skips gracefully (no blocking) if the build tool isn't on PATH.
- **create_pull_request** — commits to a `testgen/...` branch, opens the PR via `gh`.
  The PR body reports the test status; if the suite still fails after 3 self-correction
  rounds the PR is opened anyway, **flagged as failing** with the remaining failures,
  so the work isn't lost and a human (plus the PR's own regression check) takes over.
  If nothing effectively changed, no PR is opened.

### Generated glue

When no existing step pattern can express a behavior, the agent proposes step-definition
files in `STEPDEF` blocks, in the detected language. Guard rails:

- must live under the test-source tree and contain real step definitions (Java
  `@Given/@When/@Then` annotations, or C# `[Given]/[When]/[Then]` attributes)
- a rewrite must preserve every step definition already in the file (checked
  whenever the file exists — the CREATE/UPDATE *label* is not load-bearing)
- shared state (last response, last-created entity ids) must use the same shared
  mechanism the existing glue uses — the `TestContext` bean (Java) or `TestState`
  (`.NET`) — never private/static fields, which are invisible across glue classes
- glue is validated structurally and then **actually compiled and run** by
  `run_generated_tests`, so a compile error or wrong assertion is caught and
  self-corrected before the PR (the PR's regression run remains the final backstop)

### Configuration (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | required |
| `TESTGEN_MODEL` | `openai/gpt-oss-120b:free` | first model in the fallback chain |
| `TESTGEN_MODELS` | — | comma-separated list replacing the whole chain |
| `TESTGEN_MAX_ATTEMPTS` | `6` | generate→validate retry safety cap |
| `TESTGEN_MAX_TEST_ATTEMPTS` | `3` | run-tests→fix retry budget |
| `TESTGEN_MAX_CONTEXT_CHARS` | `60000` | per-section context cap |
| `TESTGEN_TEST_TIMEOUT` | `900` | seconds before a `mvn test` / `dotnet test` run is killed |

The build/test command, component directory, and glue language are **not** env vars
— they come from the detected `LanguageProfile`. The execution loop is skipped (not
failed) if the build tool (`mvn` / `dotnet`) isn't on PATH.

**Ticket context (Azure DevOps) — all optional:**

| Variable | Purpose |
|---|---|
| `ADO_ORG` | ADO organization — required to fetch work items |
| `AZURE_DEVOPS_PAT` (or `ADO_PAT`) | Personal access token (Work Items: Read) — required to fetch |
| `ADO_PROJECT` | Project name/id (optional for get-by-id) |
| `ADO_BASE_URL` | Override for Azure DevOps Server / on-prem (default `https://dev.azure.com`) |

When unset, the agent runs exactly as before with empty ticket context. The work
item to fetch is taken from `--work-item` or auto-detected from `AB#123` references
in the commit messages. Reviewer guidance is supplied via `--reviewer-input` /
`--reviewer-input-file`, and is also augmented by the work-item's comments.

### Agent tests

```bash
cd testgen-agent
.venv/bin/python -m unittest discover tests
```

### Run the agent locally

```bash
cd testgen-agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export OPENROUTER_API_KEY=...

# Dry run: write feature/glue files locally, no branch/commit/PR
.venv/bin/python main.py --repo .. --base HEAD~1 --head HEAD --no-pr

# Full run (needs a GitHub remote + gh auth)
.venv/bin/python main.py --repo .. --base HEAD~1 --head HEAD

# With ticket context + reviewer guidance (ADO_ORG/AZURE_DEVOPS_PAT in env):
.venv/bin/python main.py --repo .. --base HEAD~1 --head HEAD --no-pr \
    --work-item 1234 \
    --reviewer-input "Cover the 100000 boundary exactly; price 100001 must 400."
```

### Run a regression suite locally

```bash
mvn -f java-component/pom.xml verify     # Java  → target/cucumber-report.html
dotnet test dotnet-component             # .NET  (requires the .NET 8 SDK)
```

The Java suite needs JDK 17+ — if `mvn` picks up an older Java, point `JAVA_HOME`
at 17 (e.g. via `~/.mavenrc`). The `dotnet-component` sample is provided as a
detection target and still needs a `dotnet test` run to verify (see its README).

## Setup for CI

1. Push this repo to GitHub.
2. Add the `OPENROUTER_API_KEY` repository secret (Settings → Secrets and variables → Actions).
3. Allow GitHub Actions to create pull requests
   (Settings → Actions → General → "Allow GitHub Actions to create and approve pull requests").

## Try the loop end to end

1. Change the component — add a validation rule, a new conditional path, or a whole
   new controller (no step definitions needed: the agent proposes its own glue).
2. Push to `main` → `generate-tests.yml` opens a PR with new/updated scenarios
   (and glue, if required).
3. **Check the PR's regression run is green, then review the Gherkin** — exact
   boundary values and error messages are where models slip, and the reviewer's
   question is "is this newly asserted behavior actually what we wanted?"
4. Merge → `regression.yml` confirms code and suite are in sync on `main`.

To replay a past diff without pushing: Actions → *Generate regression tests* →
Run workflow, setting `base` to the commit before the change.

## Review checklist for generated PRs

- Regression check green? (Never merge red — that's how broken scenarios get in.)
- Expected values match the source exactly (validation messages, computed totals,
  boundary sides)?
- New glue uses the shared-state mechanism (`TestContext` / `TestState`) and the
  "last created <entity>" idiom?
- Scenarios that *should* exist aren't missing (each changed/added endpoint covered,
  happy + unhappy paths)?

## Limitations

### How much change one run can handle

Generation is a **single LLM call** — no chunking, no multi-pass. That sets the
ceilings:

| Limit | Value | Effect when exceeded |
|---|---|---|
| Git diff in the prompt | 60,000 chars (`TESTGEN_MAX_CONTEXT_CHARS`) | Diff is silently truncated; changes past the cut-off are invisible to the model |
| Component source in the prompt | 60,000 chars | Changed files survive (ordered first); stale-assertion detection over unchanged files degrades. Roughly 80–100+ Java files won't fit |
| Existing features + glue in the prompt | 60,000 chars | Step-reuse alignment weakens on very large suites |
| Generated output | free-tier completion caps (~4–16K tokens) | Roughly 3–6 files per run; bigger asks truncate mid-output → parse failure → retries exhausted |

The quality ceiling arrives **before** the mechanical ones: with free models the
sweet spot is **1–3 endpoints' worth of behavioral change per push**. Beyond
~5 endpoints or several interacting business rules in one diff, coverage gets
shallow and boundary/arithmetic errors multiply faster than the retry loop can
correct. Note it is *behavioral density*, not diff size, that matters — a
3,000-line mechanical refactor with no API change is handled correctly
("purely internal, no tests"), while a 40-line diff adding three interacting
pricing rules is the hard case.

Working within it:
- Merge one feature at a time — batch size per run equals push size.
- For a big change already merged, replay it in slices: Run workflow with `base`
  set to intermediate commits.
- To raise the ceilings: a stronger paid model (`TESTGEN_MODEL`, e.g.
  `anthropic/claude-haiku-4.5`) roughly doubles handleable complexity; raising
  `TESTGEN_MAX_CONTEXT_CHARS` helps input but not output or model depth. The
  structural fix for large components is one generation call per impacted
  controller (fan-out in the graph) — not implemented.

### What validation can and cannot catch

The validator guarantees *structure*, not *meaning*:

- **Caught pre-PR**: undefined steps (no matching glue), bad Outline placeholders,
  type-incompatible Examples values, CREATE/UPDATE mismatches, glue that drops
  existing step definitions, paths outside the test tree.
- **Caught by the execution-feedback loop** (`run_generated_tests`, before the PR):
  glue that doesn't compile and scenarios that fail against the real API (wrong
  status codes, messages, totals) — the agent runs the test command, reads the
  failures, and regenerates up to 3 times. Only failures that survive all 3 rounds
  reach the PR (flagged as failing).
- **Still caught by the PR's regression run** (defense in depth): anything the
  local loop's environment didn't reproduce.
- **Caught only by a human reviewer**: expected values that are plausible but wrong
  (a boundary on the wrong side, an approximated error message, a discount applied
  after instead of before a cap), missing coverage, and tests that "bless" an
  accidental behavior change as intended. When a run fails after all retries the
  workflow goes red with clear logs — but a *shallow-but-valid* PR will pass
  validation, which is why the review checklist above exists.

### Other constraints

- Free OpenRouter models are shared pools: upstream 429s and catalog removals
  happen without notice. The model fallback chain + backoff absorbs most of it,
  but a congested hour can still fail a run (re-run from the Actions tab).
- The agent only reacts to a component's **source** changes (`java-component/src/main/**`,
  `dotnet-component/Api/**`) — behavior driven from config files (`application.yml`,
  SQL, `appsettings.json`) is invisible to it.
- Step matching supports common cucumber-expression and regex step syntax; custom
  parameter types match loosely, so a wrong-format argument reaches the PR check.
- Two components (Java + .NET) are wired today. Adding another stack is one
  `LanguageProfile` in `languages.py` plus workflow path entries — the nodes are
  language-agnostic.
- The `dotnet-component` sample was authored without the .NET SDK and still needs a
  `dotnet test` run to confirm it builds; the agent's .NET support (detection, C#
  glue parsing, `dotnet test` runner + failure parsing) is unit-tested independently.
