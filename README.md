# AI-Generated Cucumber Regression Tests

A pipeline that keeps a Cucumber regression suite in sync with a Java REST component.
When the component's code changes, a Python LangGraph agent analyzes the git diff with
Claude, generates/updates `.feature` files, and opens a PR. After manual review and
merge, the regression suite runs in CI against the new code.

## Flow

```
developer changes Java code
        │  (push / merge to main)
        ▼
[generate-tests.yml]  →  LangGraph agent:
        │                  git diff → gather context → Claude generates Gherkin
        │                  → validate (retry up to 3×) → write .feature files
        ▼
PR with new/updated regression tests  ──▶  manual review  ──▶  merge
        │
        ▼
[regression.yml]  →  mvn verify  →  Cucumber suite runs against the new code
```

## Repository layout

| Path | What it is |
|---|---|
| `java-component/` | The component under test: a Spring Boot Product CRUD API (`/api/v1/products`) with bean validation and a `@RestControllerAdvice` error handler |
| `java-component/src/test/resources/features/` | The Cucumber regression suite (what the agent maintains) |
| `java-component/src/test/java/.../ProductStepDefinitions.java` | Reusable, parameterized step definitions the generated Gherkin must align to |
| `testgen-agent/` | Python LangGraph agent that generates the tests |
| `.github/workflows/generate-tests.yml` | Runs the agent when `src/main` code changes; opens the test PR |
| `.github/workflows/regression.yml` | Runs `mvn verify` (the Cucumber suite) on every push/PR touching the component |

## The agent (testgen-agent/)

LangGraph state machine:

`collect_diff → gather_context → generate_tests → validate_output → write_features → create_pull_request`

- **collect_diff** — `git diff base..head`; exits early if no Java main-source changes.
  Handles CI edge cases: all-zero `before` SHA (first push), force-pushed/unreachable
  base (falls back to `head~1`, then the empty tree for single-commit repos).
- **gather_context** — reads the full component source (changed files first), the
  Java glue code (found by `@Given/@When/@Then` content, not file naming), every
  existing `.feature` file, and an OpenAPI spec if present. Skips `target/`, venvs, etc.
- **generate_tests** — calls the model via OpenRouter with a fallback chain
  (`TESTGEN_MODELS`), JSON mode when supported, exponential backoff on 429s, and
  typed status-code handling. Malformed JSON or schema mismatches don't crash —
  they re-enter the retry loop as feedback to the model.
- **validate_output** — structural Gherkin checks (Feature/Scenario present, Outline
  has Examples, paths under `features/`, CREATE vs UPDATE consistency, duplicate
  files) **plus step-definition matching**: every generated step (including
  Scenario Outline steps with `<placeholder>` substitution) must match a cucumber
  expression parsed from the Java glue, or the exact offending step is fed back to
  the model. Up to `TESTGEN_MAX_ATTEMPTS` (default 3) attempts.
- **write_features / create_pull_request** — writes files (skipping content-identical
  ones), commits to a `testgen/...` branch, opens the PR via `gh`. If the generated
  suite is byte-identical to the existing one, no PR is opened.

The agent can also propose **Java step definitions** (`new_or_modified_step_definitions`)
when no existing step pattern can express a behavior. Guard rails: glue must live
under `src/test/java/`, must contain real `@Given/@When/@Then` annotations, and an
UPDATE must preserve every step definition already in the file. Steps in generated
scenarios may reference either existing glue or glue proposed in the same generation.

### Configuration (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | required |
| `TESTGEN_MODEL` | `openai/gpt-oss-120b:free` | first model in the fallback chain |
| `TESTGEN_MODELS` | — | comma-separated list replacing the whole chain |
| `TESTGEN_MAX_ATTEMPTS` | `3` | generate→validate retry budget |
| `TESTGEN_MAX_CONTEXT_CHARS` | `60000` | per-section context cap |

### Agent tests

```bash
cd testgen-agent
.venv/bin/python -m unittest discover tests
```

### Run locally

```bash
cd testgen-agent
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

# Dry run: write feature files, no branch/commit/PR
python main.py --repo .. --base HEAD~1 --head HEAD --no-pr

# Full run (needs a GitHub remote + gh auth)
python main.py --repo .. --base HEAD~1 --head HEAD
```

### Run the regression suite locally

```bash
mvn -f java-component/pom.xml verify
```

HTML report: `java-component/target/cucumber-report.html`.

## Setup for CI

1. Push this repo to GitHub.
2. Add the `ANTHROPIC_API_KEY` repository secret (Settings → Secrets and variables → Actions).
3. Allow GitHub Actions to create pull requests
   (Settings → Actions → General → "Allow GitHub Actions to create and approve pull requests").

## Try the loop end to end

1. Change the component — e.g. add a `@Size(min = 3)` constraint to `ProductRequest.name`,
   or add a new `GET /api/v1/products/search?name=` endpoint.
2. Merge that change to `main` → `generate-tests.yml` opens a PR with new/updated scenarios.
3. Review the Gherkin, merge the PR → `regression.yml` runs the suite against the new code.
