"""LangGraph nodes for the Cucumber regression test-generation pipeline."""

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI
from pydantic import ValidationError

from .gherkin import extract_step_patterns, find_undefined_steps
from .prompts import RETRY_SUFFIX_TEMPLATE, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from .state import GenerationResult, TestGenState

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = int(os.environ.get("TESTGEN_MAX_ATTEMPTS", "3"))

# Per-section guardrail for very large diffs/sources. ~15K tokens per section —
# comfortably inside the 131K-token windows of the free models below, but large
# enough that the full component source + features + step definitions fit.
MAX_CONTEXT_CHARS = int(os.environ.get("TESTGEN_MAX_CONTEXT_CHARS", "60000"))

# Free models are shared pools and get rate-limited upstream (429) without warning.
# Tried in order; on 429/5xx the next model is attempted, so one congested pool
# doesn't fail the whole run. Override the whole chain with TESTGEN_MODELS
# (comma-separated) or just the first choice with TESTGEN_MODEL.
if os.environ.get("TESTGEN_MODELS"):
    MODELS = [m.strip() for m in os.environ["TESTGEN_MODELS"].split(",") if m.strip()]
else:
    MODELS = [
        os.environ.get("TESTGEN_MODEL", "openai/gpt-oss-120b:free"),
        "openai/gpt-oss-20b:free",
        "google/gemma-4-26b-a4b-it:free",
    ]

JAVA_SOURCE_MARKER = "src/main/java"
JAVA_TEST_MARKER = "src/test/java"
FEATURES_DIR_MARKER = "src/test/resources/features"

# GitHub sends this as `before` on the first push to a branch.
_ZERO_SHA = re.compile(r"^0{7,40}$")
# git's well-known hash of the empty tree: diffing against it shows every file
# as added, which is the correct "everything is new" baseline.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# Directories that should never feed the model or the validators.
_SKIP_DIRS = {".git", "target", "build", "node_modules", ".venv", "venv", ".idea"}


def _run(cmd: list, cwd: str) -> str:
    """Run a command; on failure raise with stderr included so CI logs are usable."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result.stdout


def _iter_repo_files(repo: Path, pattern: str):
    """rglob that skips build output, virtualenvs, and VCS internals."""
    for path in sorted(repo.rglob(pattern)):
        if not any(part in _SKIP_DIRS for part in path.relative_to(repo).parts):
            yield path


def _read(path: Path) -> str:
    # errors="replace": a stray non-UTF8 byte in one file shouldn't kill the run.
    return path.read_text(encoding="utf-8", errors="replace")


def _ref_exists(repo: str, ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=repo, capture_output=True,
        ).returncode
        == 0
    )


def _resolve_base(repo: str, base: str, head: str) -> str:
    """Make the base ref usable.

    Handles the CI edge cases: GitHub sends an all-zero `before` SHA on the
    first push to a branch, and a force-push can make `before` unreachable.
    Fall back to the head's parent, and for a single-commit repo to the empty
    tree (so the whole component counts as changed).
    """
    if not _ZERO_SHA.match(base) and _ref_exists(repo, base):
        return base
    if _ref_exists(repo, f"{head}~1"):
        logger.warning("base %r unusable; falling back to %s~1", base, head)
        return f"{head}~1"
    logger.warning("base %r unusable and %s has no parent; diffing against empty tree", base, head)
    return _EMPTY_TREE


def collect_diff(state: TestGenState) -> TestGenState:
    """Compute the git diff between base and head and list changed files."""
    repo = state["repo_path"]
    head = state["head_ref"]

    if not _ref_exists(repo, head):
        raise RuntimeError(f"head ref {head!r} does not exist in {repo}")
    base = _resolve_base(repo, state["base_ref"], head)

    diff = _run(["git", "diff", f"{base}..{head}", "--", "."], cwd=repo)
    changed = _run(["git", "diff", "--name-only", f"{base}..{head}"], cwd=repo)
    changed_files = [line.strip() for line in changed.splitlines() if line.strip()]

    java_changes = [f for f in changed_files if JAVA_SOURCE_MARKER in f and f.endswith(".java")]
    update: TestGenState = {"git_diff": diff, "changed_files": changed_files}
    if not java_changes:
        update["skipped_reason"] = (
            "No Java main-source changes between "
            f"{base} and {head}; nothing to generate tests for."
        )
    return update


def gather_context(state: TestGenState) -> TestGenState:
    """Read source files, glue code, existing features, and any API spec."""
    repo = Path(state["repo_path"])
    changed_files = state["changed_files"]

    # All main-source Java files, with the changed ones FIRST so truncation by
    # MAX_CONTEXT_CHARS sacrifices the least relevant context. The model needs
    # the unchanged files too: stale-assertion detection means executing the
    # existing scenarios against the post-change code, and the behavior an
    # assertion depends on often lives outside the diffed files.
    changed_java = [
        rel for rel in changed_files
        if JAVA_SOURCE_MARKER in rel and rel.endswith(".java")
    ]
    other_java = [
        str(p.relative_to(repo))
        for p in _iter_repo_files(repo, "*.java")
        if JAVA_SOURCE_MARKER in str(p) and str(p.relative_to(repo)) not in changed_java
    ]
    sources: list = []
    for rel in changed_java + other_java:
        path = repo / rel
        if path.is_file():
            marker = "CHANGED IN THIS DIFF" if rel in changed_java else "unchanged"
            sources.append(f"// FILE ({marker}): {rel}\n{_read(path)}")

    # Glue code is the reuse contract. Find it by content (any test-source file
    # with @Given/@When/@Then annotations), not by file-naming convention, and
    # keep the parsed cucumber expressions for the post-generation validator.
    step_patterns: list = []
    for java in _iter_repo_files(repo, "*.java"):
        rel = str(java.relative_to(repo))
        if JAVA_TEST_MARKER not in rel:
            continue
        text = _read(java)
        patterns = extract_step_patterns(text)
        if patterns:
            step_patterns.extend(patterns)
            sources.append(f"// FILE (step definitions): {rel}\n{text}")
    if not step_patterns:
        logger.warning("no step definitions found — undefined-step validation disabled")

    features: list = []
    for feature in _iter_repo_files(repo, "*.feature"):
        rel = feature.relative_to(repo)
        features.append(f"# FILE: {rel}\n{_read(feature)}")

    api_spec = ""
    for candidate in ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml", "swagger.json"):
        matches = list(_iter_repo_files(repo, candidate))
        if matches:
            api_spec = _read(matches[0])
            break

    return {
        "target_component_context": "\n\n".join(sources)[:MAX_CONTEXT_CHARS],
        "existing_feature_examples": "\n\n".join(features)[:MAX_CONTEXT_CHARS],
        "api_spec": api_spec[:MAX_CONTEXT_CHARS] or "Not available.",
        "step_patterns": step_patterns,
        "attempts": 0,
        "validation_errors": [],
    }


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text.strip())
    return text


def _parse_generation(raw_text: str) -> GenerationResult:
    """Parse model output into a GenerationResult; raise ValueError with a
    model-actionable message on any failure."""
    text = _strip_markdown_fences(raw_text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the outermost brace pair (models sometimes add prose).
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("no JSON object found in the response")
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise ValueError(f"response contained invalid JSON: {e}")
    try:
        return GenerationResult.model_validate(parsed)
    except ValidationError as e:
        compact = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise ValueError(f"JSON did not match the required schema: {compact}")


def generate_tests(state: TestGenState) -> TestGenState:
    """Call the model (with model fallback + backoff) and parse its output.

    Parse failures do NOT crash the run: they are returned as validation_errors
    so the graph's retry loop feeds them back to the model, exactly like Gherkin
    validation failures.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "your-app",
            "X-Title": "testgen-agent",
        },
    )

    user_prompt = USER_PROMPT_TEMPLATE.format(
        target_component_context=state["target_component_context"],
        git_diff=state["git_diff"][:MAX_CONTEXT_CHARS],
        existing_feature_examples=state["existing_feature_examples"],
        api_spec=state["api_spec"],
    )

    if state.get("validation_errors"):
        errors = "\n".join(f"- {e}" for e in state["validation_errors"])
        user_prompt += RETRY_SUFFIX_TEMPLATE.format(errors=errors)

    full_prompt = f"""
    {SYSTEM_PROMPT}

    {user_prompt}

    IMPORTANT:
    Return ONLY valid JSON in this format:
    {{
    "analysis_summary": "string",
    "impacted_endpoints": ["string"],
    "new_or_modified_features": [
        {{
        "file_name": "string",
        "action": "CREATE or UPDATE",
        "gherkin_content": "string"
        }}
    ]
    }}
    """

    response_text: Optional[str] = None
    last_error: Optional[Exception] = None

    # Outer loop: fall back across models. Inner loop: retry each model with
    # exponential backoff (5s, 20s) — free-pool 429s usually clear in seconds.
    for model in MODELS:
        json_mode = True  # ask for JSON mode; drop it if the model rejects it
        retries_left = 3
        while retries_left > 0 and response_text is None:
            try:
                kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": full_prompt}],
                    temperature=0,
                    **kwargs,
                )
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise ValueError("model returned an empty response")
                response_text = content
                logger.info("Generated with model %s", model)
            except Exception as e:
                last_error = e
                # Typed status from the SDK; substring checks on str(e) can
                # false-positive (digits appear in IDs and token counts).
                status = getattr(e, "status_code", None)
                logger.warning("[%s] failed (status=%s): %s", model, status, e)
                if status == 402:
                    raise RuntimeError("OpenRouter billing required") from e
                if status == 404:
                    break  # model removed from catalog — next model
                if status == 400:
                    if json_mode:
                        json_mode = False  # model rejects response_format; free retry
                        continue
                    break  # request shape rejected — next model
                retries_left -= 1
                if retries_left > 0:
                    time.sleep(5 * 4 ** (2 - retries_left))  # 5s, then 20s
        if response_text is not None:
            break

    if response_text is None:
        raise RuntimeError(
            f"All models exhausted ({', '.join(MODELS)}). Last error: {last_error}"
        )

    attempts = state.get("attempts", 0) + 1
    try:
        generation = _parse_generation(response_text)
    except ValueError as e:
        logger.warning("attempt %d produced unparseable output: %s", attempts, e)
        return {
            "generation": None,
            "attempts": attempts,
            "validation_errors": [
                f"Your previous response could not be used: {e}. "
                "Return exactly ONE JSON object matching the schema, with no "
                "surrounding prose or markdown fences."
            ],
        }
    return {"generation": generation, "attempts": attempts, "validation_errors": []}


def validate_output(state: TestGenState) -> TestGenState:
    """Validate generated Gherkin (structure, paths, CREATE/UPDATE consistency,
    and that every step matches an existing step definition)."""
    generation = state.get("generation")
    if generation is None:
        # generate_tests already recorded parse errors; pass them through.
        return {}

    repo = Path(state["repo_path"]).resolve()
    step_patterns = state.get("step_patterns", [])
    errors: list = []

    seen_names = set()
    for feature in generation.new_or_modified_features:
        name = feature.file_name.lstrip("./")
        target = (repo / name).resolve()

        if name in seen_names:
            errors.append(f"{name}: appears more than once in new_or_modified_features")
        seen_names.add(name)

        if not name.endswith(".feature"):
            errors.append(f"{name}: file name must end with .feature")
        if FEATURES_DIR_MARKER not in name:
            errors.append(f"{name}: must live under {FEATURES_DIR_MARKER}/")
        if not target.is_relative_to(repo):
            errors.append(f"{name}: path escapes the repository root")
        if feature.action == "UPDATE" and not target.is_file():
            errors.append(f"{name}: action is UPDATE but the file does not exist (use CREATE)")
        if feature.action == "CREATE" and target.is_file():
            errors.append(f"{name}: action is CREATE but the file already exists (use UPDATE)")

        lines = [line.strip() for line in feature.gherkin_content.splitlines()]
        if not any(line.startswith("Feature:") for line in lines):
            errors.append(f"{name}: content has no 'Feature:' declaration")
        if not any(line.startswith(("Scenario:", "Scenario Outline:")) for line in lines):
            errors.append(f"{name}: content has no scenarios")
        outline_count = sum(1 for line in lines if line.startswith("Scenario Outline:"))
        examples_count = sum(1 for line in lines if line.startswith("Examples:"))
        if outline_count > examples_count:
            errors.append(f"{name}: a Scenario Outline is missing its Examples table")

        # The reuse contract: every step must have glue code, or Cucumber will
        # fail the PR with undefined steps. Feed exact offenders back.
        if step_patterns:
            for step in find_undefined_steps(feature.gherkin_content, step_patterns):
                errors.append(
                    f'{name}: step "{step}" matches no existing step definition. '
                    "Rephrase it using one of the step patterns from the "
                    "provided step definitions file."
                )

    if errors:
        logger.warning("Validation failed (attempt %d): %s", state["attempts"], errors)
    return {"validation_errors": errors}


def write_features(state: TestGenState) -> TestGenState:
    """Write the validated feature files; skip files whose content is unchanged."""
    repo = Path(state["repo_path"])
    written: list = []
    for feature in state["generation"].new_or_modified_features:
        target = repo / feature.file_name.lstrip("./")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = feature.gherkin_content.replace("\r\n", "\n")
        if not content.endswith("\n"):
            content += "\n"
        if target.is_file() and _read(target) == content:
            logger.info("UNCHANGED %s (generated content identical; skipping)", feature.file_name)
            continue
        target.write_text(content, encoding="utf-8")
        written.append(str(target.relative_to(repo)))
        logger.info("%s %s", feature.action, feature.file_name)
    return {"written_files": written}


def create_pull_request(state: TestGenState) -> TestGenState:
    """Commit the generated features on a new branch and open a PR via the gh CLI."""
    repo = state["repo_path"]
    generation = state["generation"]

    if not state["written_files"]:
        logger.info("no feature files changed on disk; skipping PR")
        return {"pr_url": None, "skipped_reason": "generated tests are identical to the existing suite"}

    head_sha = _run(["git", "rev-parse", "--short=12", state["head_ref"]], cwd=repo).strip()
    branch = f"testgen/{head_sha}-{int(time.time())}"

    original_ref = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).strip()
    _run(["git", "checkout", "-b", branch], cwd=repo)
    try:
        _run(["git", "add", *state["written_files"]], cwd=repo)
        staged = _run(["git", "diff", "--cached", "--name-only"], cwd=repo).strip()
        if not staged:
            logger.info("nothing staged after add; skipping PR")
            return {"pr_url": None, "skipped_reason": "no effective changes to commit"}
        _run(
            ["git", "commit", "-m",
             "test: regenerate Cucumber regression tests\n\n" + generation.analysis_summary],
            cwd=repo,
        )
        _run(["git", "push", "-u", "origin", branch], cwd=repo)

        endpoints = "\n".join(f"- `{e}`" for e in generation.impacted_endpoints) or "- none"
        body = (
            "## Auto-generated regression tests\n\n"
            f"{generation.analysis_summary}\n\n"
            f"### Impacted endpoints\n{endpoints}\n\n"
            f"### Files\n" + "\n".join(f"- `{f}`" for f in state["written_files"]) + "\n\n"
            "Please review the scenarios before merging. Regression runs automatically "
            "after merge.\n\n"
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
        )
        pr_url = _run(
            ["gh", "pr", "create",
             "--title", "test: update Cucumber regression suite for latest code changes",
             "--body", body,
             "--head", branch],
            cwd=repo,
        ).strip()
        logger.info("Opened PR: %s", pr_url)
        return {"pr_url": pr_url}
    finally:
        # Best-effort return to where we started (matters for local runs;
        # harmless in CI). "HEAD" means we began detached — stay put then.
        if original_ref != "HEAD":
            subprocess.run(["git", "checkout", original_ref], cwd=repo, capture_output=True)
