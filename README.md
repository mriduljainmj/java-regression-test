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
- **run_generated_tests** — runs `mvn test` on what was just written. On failure
  it parses **both** Java compile errors and per-scenario Cucumber failures
  (feature → scenario → failing step → assertion message) and feeds them back to
  `generate_tests`, looping up to `TESTGEN_MAX_TEST_ATTEMPTS` (default 3) times.
  This is the execution-feedback loop: it catches the *semantic* errors static
  validation can't — a wrong expected value, a miscomputed total, glue that
  doesn't compile. Skips gracefully (no blocking) if Maven isn't on PATH, so the
  agent still runs in a Maven-less environment, just without this loop.
- **write_features / create_pull_request** — writes files (skipping content-identical
  ones), commits to a `testgen/...` branch, opens the PR via `gh`. The PR body
  reports the test status; if the suite still fails after 3 self-correction
  rounds the PR is opened anyway, **flagged as failing** with the remaining
  failures, so the work isn't lost and a human (plus the PR's own regression
  check) takes over. If nothing effectively changed, no PR is opened.

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
| `TESTGEN_MAX_ATTEMPTS` | `6` | generate→validate retry safety cap |
| `TESTGEN_MAX_TEST_ATTEMPTS` | `3` | run-tests→fix retry budget |
| `TESTGEN_MAX_CONTEXT_CHARS` | `60000` | per-section context cap |
| `MAVEN_CMD` | `mvn` | Maven binary; loop is skipped if not found |
| `TESTGEN_COMPONENT_DIR` | `java-component` | component whose `mvn test` runs |

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
2. If the change is tied to an Azure DevOps ticket, include the work item id in the
  commit/merge message as `AB#1234` or set `AZDO_WORK_ITEM_ID` so the generator can
  pull title/description/acceptance criteria into the test prompt and PR body.
3. Push to `main` → `generate-tests.yml` opens a PR with new/updated scenarios
   (and glue, if required).
4. **Check the PR's regression run is green, then review the Gherkin** — exact
   boundary values and error messages are where models slip, and the reviewer's
   question is "is this newly asserted behavior actually what we wanted?"
5. Merge → `regression.yml` confirms code and suite are in sync on `main`.

### Azure DevOps integration

To enrich generated tests with ADO ticket context, configure these repository
secrets in GitHub Actions:

- `AZDO_ORG_URL` - your Azure DevOps organization URL, e.g. `https://dev.azure.com/your-org`
- `AZDO_PROJECT` - your Azure DevOps project name
- `AZDO_PAT` - a PAT with work item read access

The generator will automatically look for a work item id in the commit/merge message
using `AB#1234`, `ADO-1234`, or `WI-1234`. You can also override it manually when
running the workflow with `workflow_dispatch`.

To replay a past diff without pushing: Actions → *Generate regression tests* →
Run workflow, setting `base` to the commit before the change.

## Review checklist for generated PRs

- Regression check green? (Never merge red — that's how broken scenarios get in.)
- Expected values match the source exactly (validation messages, computed totals,
  boundary sides)?
- New glue uses `TestContext` and the "last created <entity>" idiom?
- Scenarios that *should* exist aren't missing (each changed/added endpoint covered,
  happy + unhappy paths)?

## Troubleshooting

### .NET SpecFlow Tests Failing - "TechTalk" Namespace Not Found

**Problem**: Compiler errors like:
```
error CS0246: The type or namespace name 'TechTalk' could not be found
error CS0246: The type or namespace name 'Binding' could not be found
```

**Solution**: Ensure BP.Tests.csproj has proper item groups:
```xml
<ItemGroup>
  <Compile Include="Tests/**/*.cs" />
</ItemGroup>

<ItemGroup>
  <SpecFlowFeatureFiles Include="Tests/Features/**/*.feature" />
</ItemGroup>
```

**Then rebuild:**
```bash
cd dotnet-component
dotnet clean
dotnet build
dotnet test
```

### Java Tests Failing - Maven Not Found

**Problem**: `mvn: command not found`

**Solution**: 
```bash
# Install Maven
brew install maven                    # Mac
sudo apt-get install maven            # Linux
choco install maven                   # Windows (admin)

# Or set MAVEN_HOME
export MAVEN_HOME=/path/to/maven
export PATH=$PATH:$MAVEN_HOME/bin
```

---

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
  Java glue that doesn't compile and scenarios that fail against the real API
  (wrong status codes, messages, totals) — the agent runs `mvn test`, reads the
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
- The agent only reacts to `java-component/src/main/**/*.java` changes — behavior
  driven from config files (`application.yml`, SQL, properties) is invisible to it.
- Step matching supports the common cucumber-expression syntax; custom parameter
  types match loosely, so a wrong-format argument reaches the PR check.
- One component per repo as wired; multiple components would need per-component
  workflow paths and prompts.

## PROJECT.md Auto-Update System

The project maintains a living AI knowledge base (`PROJECT.md`) that stays in sync with code
changes automatically. This ensures the testgen-agent always has current API definitions,
business logic details, and edge cases without re-exploring the codebase.

### How It Works

```
Developer changes code (Java, .NET, or feature file)
        │
        ├─ Local: git pre-commit hook runs (optional)
        │  └─ update-project-mindmap.py detects changes
        │     └─ PROJECT.md auto-updated + staged
        │
        ▼
Developer pushes to develop/main
        │
        ├─ GitHub Actions: auto-update-mindmap.yml triggers
        │  └─ update-project-mindmap.py runs
        │     ├─ Scans controllers for API endpoints
        │     ├─ Scans services for business logic
        │     ├─ Scans features for test scenarios
        │     └─ Updates PROJECT.md + auto-commits
        │
        ▼
PROJECT.md is current
        │
        ├─ testgen-agent reads PROJECT.md on next run
        │  └─ Has all current APIs, methods, test patterns
        │     └─ Generates accurate tests without codebase exploration
```

### What Gets Updated Automatically

| File Change | Detects | Updates |
|---|---|---|
| `*Controller.java` | `@GetMapping`, `@PostMapping`, `@PutMapping`, `@DeleteMapping` | API endpoints in PROJECT.md PART 2 |
| `*Controller.cs` | `[HttpGet]`, `[HttpPost]`, `[HttpPut]`, `[HttpDelete]` | API endpoints in PROJECT.md PART 2 |
| `*Service.java` | Public method signatures | Service logic in PROJECT.md PART 3 |
| `*Service.cs` | Public method signatures | Service logic in PROJECT.md PART 3 |
| `*.feature` | Scenario names and counts | Test coverage in PROJECT.md PART 5 |

Each auto-update is marked with `[AUTO-UPDATE]` prefix in PROJECT.md so you know which
sections were machine-generated vs. manually maintained.

### Setup (One-Time)

**Windows:**
```bash
setup-hooks.bat
```

**Mac/Linux:**
```bash
./setup-hooks.sh
```

This configures git to use the `.githooks/` directory and enables the pre-commit hook.

### Example: Add a New Endpoint

1. **Edit Java controller:**
   ```java
   @PostMapping("/{id}/apply-loyalty")
   public void applyLoyalty(@PathVariable Long id) { }
   ```

2. **Commit:**
   ```bash
   git add java-component/src/main/java/com/example/products/ProductController.java
   git commit -m "feat: add loyalty endpoint"
   ```

3. **What happens:**
   - Pre-commit hook runs
   - `update-project-mindmap.py` detects new endpoint
   - PROJECT.md updated with:
     ```
     [AUTO-UPDATE] Java endpoints detected:
     - POST /api/v1/products/{id}/apply-loyalty (applyLoyalty)
     ```
   - PROJECT.md auto-staged

4. **Push:**
   ```bash
   git push origin develop
   ```

5. **CI verifies:**
   - `auto-update-mindmap.yml` runs
   - Double-checks PROJECT.md is current
   - Auto-commits if any updates needed

6. **Next AI run:**
   - testgen-agent reads PROJECT.md
   - Sees new endpoint immediately
   - Generates loyalty tests

### Configuration Files

| File | Purpose |
|---|---|
| `update-project-mindmap.py` | Python script that scans and updates PROJECT.md |
| `.github/workflows/auto-update-mindmap.yml` | CI/CD workflow (GitHub Actions) |
| `.githooks/pre-commit` | Local pre-commit hook (optional) |
| `PROJECT.md` | AI knowledge base (auto-updated) |
| `AUTO-UPDATE-GUIDE.md` | Complete auto-update documentation |

### Manual Updates

Update PROJECT.md anytime without committing:
```bash
python3 update-project-mindmap.py
```

Auto-commit the changes:
```bash
python3 update-project-mindmap.py --auto-commit
```

### Benefits for testgen-agent

✅ **Accurate API Catalog** — Agent knows every endpoint immediately  
✅ **Current Business Logic** — Discount tiers, validation rules stay synced  
✅ **Test Pattern Alignment** — Existing scenarios inform new tests  
✅ **No Codebase Exploration** — Faster generation, fewer errors  
✅ **Timestamped** — Audit trail of when knowledge base was updated  

### See Also

- [PROJECT.md](PROJECT.md) — AI knowledge base
- [AUTO-UPDATE-GUIDE.md](AUTO-UPDATE-GUIDE.md) — Complete auto-update system documentation
