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
from .prompts import (
    OUTPUT_FORMAT_INSTRUCTIONS,
    RETRY_SUFFIX_TEMPLATE,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
)
from .state import FeatureFile, GenerationResult, StepDefinitionFile, TestGenState

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = int(os.environ.get("TESTGEN_MAX_ATTEMPTS", "4"))

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


_FILE_BLOCK_RE = re.compile(
    r"===\s*(FEATURE|STEPDEF)\s+(CREATE|UPDATE)\s+(\S+)\s*===\s*\n(.*?)\n\s*===\s*END\s*===",
    re.DOTALL | re.IGNORECASE,
)


def _parse_file_blocks(text: str) -> GenerationResult:
    """Parse the delimited-block output format (the preferred format: raw file
    contents need no escaping, which weak models reliably get wrong in JSON)."""
    analysis_match = re.search(r"^ANALYSIS:\s*(.+)$", text, re.MULTILINE)
    endpoints_match = re.search(r"^ENDPOINTS:\s*(.+)$", text, re.MULTILINE)
    blocks = _FILE_BLOCK_RE.findall(text)

    if not blocks and not analysis_match:
        raise ValueError(
            "no '=== FEATURE|STEPDEF CREATE|UPDATE <path> ===' file blocks and "
            "no ANALYSIS line found"
        )

    endpoints = []
    if endpoints_match:
        endpoints = [e.strip() for e in endpoints_match.group(1).split(",")
                     if e.strip() and e.strip().lower() not in ("none", "n/a")]

    features, stepdefs = [], []
    for kind, action, path, content in blocks:
        if kind.upper() == "FEATURE":
            features.append(FeatureFile(
                file_name=path, action=action.upper(), gherkin_content=content,
            ))
        else:
            stepdefs.append(StepDefinitionFile(
                file_name=path, action=action.upper(), java_content=content,
            ))

    return GenerationResult(
        impacted_endpoints=endpoints,
        analysis_summary=analysis_match.group(1).strip() if analysis_match else "",
        new_or_modified_features=features,
        new_or_modified_step_definitions=stepdefs,
    )


def _repair_json_escapes(text: str) -> str:
    """Escape lone backslashes that aren't valid JSON escapes — the most common
    model error when Java source ends up inside a JSON string."""
    return re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)


def _parse_json(text: str) -> GenerationResult:
    """Legacy JSON format, kept as a fallback for models that emit it anyway."""
    candidates = [text]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match and match.group(0) != text:
        candidates.append(match.group(0))
    candidates += [_repair_json_escapes(c) for c in list(candidates)]

    parsed = None
    last_err = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            break
        except json.JSONDecodeError as e:
            last_err = e
    if parsed is None:
        raise ValueError(f"response contained invalid JSON: {last_err}")
    try:
        return GenerationResult.model_validate(parsed)
    except ValidationError as e:
        compact = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise ValueError(f"JSON did not match the required schema: {compact}")


def _parse_generation(raw_text: str) -> GenerationResult:
    """Parse model output into a GenerationResult; raise ValueError with a
    model-actionable message on any failure."""
    text = _strip_markdown_fences(raw_text)

    # Preferred: delimited file blocks. Fallback: legacy JSON.
    if _FILE_BLOCK_RE.search(text) or text.lstrip().upper().startswith("ANALYSIS:"):
        try:
            return _parse_file_blocks(text)
        except (ValueError, ValidationError) as block_err:
            if not text.lstrip().startswith("{"):
                raise ValueError(str(block_err))
    if text.lstrip().startswith("{"):
        return _parse_json(text)
    return _parse_file_blocks(text)  # raises with the block-format guidance


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

    {OUTPUT_FORMAT_INSTRUCTIONS}
    """

    response_text: Optional[str] = None
    last_error: Optional[Exception] = None

    # Outer loop: fall back across models. Inner loop: retry each model with
    # exponential backoff (5s, 20s) — free-pool 429s usually clear in seconds.
    for model in MODELS:
        retries_left = 3
        while retries_left > 0 and response_text is None:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": full_prompt}],
                    temperature=0,
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
                if status in (400, 404):
                    break  # bad request shape or model removed — next model
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
                "Follow the OUTPUT FORMAT exactly: an ANALYSIS line, an ENDPOINTS "
                "line, then one '=== FEATURE|STEPDEF CREATE|UPDATE <path> ===' "
                "block per file ending with '=== END ==='. Raw file contents only "
                "— no JSON, no markdown fences."
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

    # Validate proposed Java glue first: its step patterns extend the set the
    # generated Gherkin is allowed to use.
    generated_patterns: list = []
    for glue in generation.new_or_modified_step_definitions:
        name = glue.file_name.lstrip("./")
        target = (repo / name).resolve()

        if name in seen_names:
            errors.append(f"{name}: appears more than once in the output")
        seen_names.add(name)

        if not name.endswith(".java"):
            errors.append(f"{name}: step-definition file name must end with .java")
        if JAVA_TEST_MARKER not in name:
            errors.append(f"{name}: step definitions must live under {JAVA_TEST_MARKER}/")
        if not target.is_relative_to(repo):
            errors.append(f"{name}: path escapes the repository root")
        if glue.action == "UPDATE" and not target.is_file():
            errors.append(f"{name}: action is UPDATE but the file does not exist (use CREATE)")
        if glue.action == "CREATE" and target.is_file():
            errors.append(f"{name}: action is CREATE but the file already exists (use UPDATE)")

        patterns_in_file = extract_step_patterns(glue.java_content)
        if not patterns_in_file:
            errors.append(
                f"{name}: contains no @Given/@When/@Then step definitions — "
                "if no new glue is needed, return an empty new_or_modified_step_definitions list"
            )
        if glue.action == "UPDATE" and target.is_file():
            removed = [
                p for p in extract_step_patterns(_read(target))
                if p not in patterns_in_file
            ]
            if removed:
                errors.append(
                    f"{name}: UPDATE removes existing step definition(s) "
                    f"{removed} — return the FULL file content preserving every "
                    "existing step"
                )
        generated_patterns.extend(patterns_in_file)

    # Steps may match existing glue OR glue proposed in this same generation.
    all_patterns = step_patterns + generated_patterns

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

        # The reuse contract: every step must have glue code — existing or
        # proposed in this generation — or Cucumber will fail the PR with
        # undefined steps. Feed exact offenders back.
        if all_patterns:
            for step in find_undefined_steps(feature.gherkin_content, all_patterns):
                message = (
                    f'{name}: step "{step}" matches no existing step definition. '
                    "Rephrase it using one of the step patterns from the provided "
                    "step definitions, or add the missing glue in a STEPDEF block."
                )
                if "<" in step:
                    message += (
                        " Note: <name> placeholders are only substituted inside "
                        "Scenario Outlines that have a matching Examples column — "
                        "in a plain Scenario, use literal values."
                    )
                errors.append(message)

    if errors:
        logger.warning("Validation failed (attempt %d): %s", state["attempts"], errors)
    return {"validation_errors": errors}


def write_features(state: TestGenState) -> TestGenState:
    """Write the validated feature and glue files; skip unchanged content."""
    repo = Path(state["repo_path"])
    generation = state["generation"]
    written: list = []

    outputs = [(f.file_name, f.action, f.gherkin_content)
               for f in generation.new_or_modified_features]
    outputs += [(g.file_name, g.action, g.java_content)
                for g in generation.new_or_modified_step_definitions]

    for file_name, action, raw_content in outputs:
        target = repo / file_name.lstrip("./")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = raw_content.replace("\r\n", "\n")
        if not content.endswith("\n"):
            content += "\n"
        if target.is_file() and _read(target) == content:
            logger.info("UNCHANGED %s (generated content identical; skipping)", file_name)
            continue
        target.write_text(content, encoding="utf-8")
        written.append(str(target.relative_to(repo)))
        logger.info("%s %s", action, file_name)
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
