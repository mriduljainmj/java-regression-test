# AI-Generated Cucumber Regression Tests

A pipeline that keeps a Cucumber regression suite in sync with a Java REST component.
When the component's code changes, a Python LangGraph agent analyzes the git diff with
an LLM (via OpenRouter), generates/updates `.feature` files — and, when needed, new
Java step definitions — then opens a PR. After manual review and merge, the regression
suite runs in CI against the new code.

## Flow

```
developer changes Java code
        │  (push to main, paths: java-component/src/main/**)
        ▼
[generate-tests.yml]  →  LangGraph agent:
        │                  git diff → gather context (source, glue, features)
        │                  → LLM generates Gherkin + Java glue (block format)
        │                  → validate (step matching, every Examples row, paths)
        │                  → retry with feedback, rotating models (up to 4×)
        │                  → write files
        ▼
PR with new/updated tests  ──▶  regression check runs ON the PR
        │                       (catches broken generated tests pre-merge)
        ▼
manual review  ──▶  merge
        │
        ▼
[regression.yml]  →  mvn verify on main  →  code and suite confirmed in sync
```

## Repository layout

| Path | What it is |
|---|---|
| `java-component/` | The component under test: Spring Boot REST API with products (CRUD + price filtering + update/delete guards), orders (tiered bulk discounts, total cap), and reviews (rating bounds, average summary) — bean validation + `@RestControllerAdvice` |
| `java-component/src/test/resources/features/` | The Cucumber regression suite (what the agent maintains) |
| `java-component/src/test/java/.../cucumber/` | Test harness: `TestContext` (shared scenario state), step-definition classes, Cucumber/Spring wiring |
| `testgen-agent/` | Python LangGraph agent that generates the tests |
| `.github/workflows/generate-tests.yml` | Runs the agent when `src/main` code changes (or manually); opens the test PR |
| `.github/workflows/regression.yml` | Runs `mvn verify` on pushes to `main` and PRs touching `java-component/` |

## When does each workflow run?

| Event | generate-tests | regression |
|---|---|---|
| Push to `main` touching `java-component/src/main/**` | ✅ (skipped for `test:` commits) | ✅ |
| Push to `main` touching only tests/features | ❌ | ✅ |
| Any PR touching `java-component/` (incl. the agent's own PRs) | ❌ | ✅ — the pre-merge safety net |
| Push touching only `testgen-agent/`, workflows, docs | ❌ | ❌ |
| Manual (Actions → Run workflow, optional `base` input) | ✅ | ❌ |

## The agent (testgen-agent/)

LangGraph state machine:

`collect_diff → gather_context → generate_tests → validate_output → write_features → create_pull_request`

- **collect_diff** — `git diff base..head`; exits early if no Java main-source changes.
  Handles CI edge cases: all-zero `before` SHA (first push), force-pushed/unreachable
  base (falls back to `head~1`, then the empty tree for single-commit repos).
- **gather_context** — reads the full component source (changed files first), the
  Java glue code (found by `@Given/@When/@Then` content, not file naming), every
  existing `.feature` file, and an OpenAPI spec if present. Skips `target/`, venvs, etc.
- **generate_tests** — calls the model via OpenRouter with a fallback chain and
  exponential backoff on 429s. Output is a **delimited block format** (raw file
  contents between `=== FEATURE|STEPDEF CREATE|UPDATE <path> === … === END ===`
  markers) — free models reliably fail to JSON-escape Java source, so JSON is only
  a tolerated fallback (with lone-backslash repair). Unparseable output re-enters
  the retry loop as feedback instead of crashing. Validation retries start from a
  **different model** in the chain to break repeated misunderstandings.
- **validate_output** — structural Gherkin checks (Feature/Scenario present, Outline
  has Examples, paths, CREATE vs UPDATE consistency, duplicates) **plus
  step-definition matching**: every generated step must match a cucumber expression
  parsed from the Java glue — existing or proposed in the same generation. Scenario
  Outline steps are checked with **every** Examples row substituted (catches `null`
  in an `{int}` column). Exact offending steps are fed back to the model, up to
  `TESTGEN_MAX_ATTEMPTS` (default 4) attempts.
- **write_features / create_pull_request** — writes files (skipping content-identical
  ones), commits to a `testgen/...` branch, opens the PR via `gh`. If nothing
  effectively changed, no PR is opened.

### Generated Java glue

When no existing step pattern can express a behavior, the agent proposes step-definition
files in `STEPDEF` blocks. Guard rails:

- must live under `src/test/java/` and contain real `@Given/@When/@Then` annotations
- an UPDATE must preserve every step definition already in the file
- shared state (last response, last created entity ids) must go through the
  scenario-scoped `TestContext` bean — private fields in one glue class are invisible
  to other glue classes, so "the last created product" steps would fail at runtime
- glue is validated structurally but **not compiled** by the agent — a Java error
  surfaces in the PR's regression check, which is why that check must be green
  before merging

### Configuration (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | required |
| `TESTGEN_MODEL` | `openai/gpt-oss-120b:free` | first model in the fallback chain |
| `TESTGEN_MODELS` | — | comma-separated list replacing the whole chain |
| `TESTGEN_MAX_ATTEMPTS` | `4` | generate→validate retry budget |
| `TESTGEN_MAX_CONTEXT_CHARS` | `60000` | per-section context cap |

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
```

### Run the regression suite locally

```bash
mvn -f java-component/pom.xml verify
```

HTML report: `java-component/target/cucumber-report.html`.
(Requires JDK 17+ — if `mvn` picks up an older Java, point `JAVA_HOME` at 17,
e.g. via `~/.mavenrc`.)

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
- New glue uses `TestContext` and the "last created <entity>" idiom?
- Scenarios that *should* exist aren't missing (each changed/added endpoint covered,
  happy + unhappy paths)?
