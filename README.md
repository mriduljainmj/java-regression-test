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
- **gather_context** — reads the full changed source files, all step definitions
  (the step-reuse contract), every existing `.feature` file, and an OpenAPI spec if present.
- **generate_tests** — calls Claude (`claude-opus-4-8`, adaptive thinking, structured
  output via a Pydantic schema) with the diff + context.
- **validate_output** — structural Gherkin checks (Feature/Scenario present, Outline
  has Examples, paths under `features/`, CREATE vs UPDATE consistency). On failure the
  errors are fed back to the model — up to 3 attempts.
- **write_features / create_pull_request** — writes files, commits to a `testgen/...`
  branch, opens the PR via `gh`.

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
