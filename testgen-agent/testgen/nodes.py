"""LangGraph nodes for the Cucumber regression test-generation pipeline."""

import json
import logging
import os
import re
import shutil
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
    TEST_FAILURE_TEMPLATE,
    USER_PROMPT_TEMPLATE,
)
from . import dotnet_prompt
from .state import FeatureFile, GenerationResult, StepDefinitionFile, TestGenState

logger = logging.getLogger(__name__)

# Safety cap on total model calls (structural retries + rotation). Set high
# enough that the execution-feedback rounds below never trip it.
# Increased to 12 for C# syntax correction retries (6 is insufficient for @Given → [Given] fixes)
MAX_ATTEMPTS = int(os.environ.get("TESTGEN_MAX_ATTEMPTS", "6"))

# Execution-feedback loop: run the generated tests and feed failures back to the
# model, at most this many times (the user-facing "max 3 retries").
MAX_TEST_ATTEMPTS = int(os.environ.get("TESTGEN_MAX_TEST_ATTEMPTS", "3"))

# Maven command + the component to test. Override MAVEN_CMD if mvn isn't on PATH.
MVN = os.environ.get("MAVEN_CMD", "mvn")
COMPONENT_DIR = os.environ.get("TESTGEN_COMPONENT_DIR", "java-component")
TEST_TIMEOUT = int(os.environ.get("TESTGEN_TEST_TIMEOUT", "900"))

# Per-section guardrail for very large diffs/sources. ~15K tokens per section —
# comfortably inside the 131K-token windows of the free models below, but large
# enough that the full component source + features + step definitions fit.
MAX_CONTEXT_CHARS = int(os.environ.get("TESTGEN_MAX_CONTEXT_CHARS", "60000"))

# Per-model retry tuning for transient OpenRouter rate limits.
MODEL_RETRIES = int(os.environ.get("TESTGEN_MODEL_RETRIES", "6"))
BACKOFF_SCHEDULE = [
    int(v.strip())
    for v in os.environ.get("TESTGEN_BACKOFF_SECONDS", "8,20,45,90,120,180").split(",")
    if v.strip()
]

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

# .NET support
CS_SOURCE_EXT = ".cs"
FEATURES_DIR_MARKER_DOTNET = "dotnet-component/Tests/Features"
DOTNET_TESTS_DIR_MARKER = "dotnet-component/Tests/"

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
    cs_changes = [f for f in changed_files if f.endswith(CS_SOURCE_EXT) or f.endswith(".csproj")]

    project_type = None
    if cs_changes:
        project_type = "dotnet"
    elif java_changes:
        project_type = "java"

    update: TestGenState = {"git_diff": diff, "changed_files": changed_files}
    if project_type is None:
        update["skipped_reason"] = (
            "No Java or C# source changes between "
            f"{base} and {head}; nothing to generate tests for."
        )
    else:
        update["project_type"] = project_type
    return update


def gather_context(state: TestGenState) -> TestGenState:
    """Read source files, glue code, existing features, and any API spec."""
    repo = Path(state["repo_path"])
    changed_files = state["changed_files"]
    project_type = state.get("project_type", "java")

    sources: list = []
    step_patterns: list = []

    if project_type == "java":
        # All main-source Java files, with changed ones first.
        changed_java = [
            rel for rel in changed_files
            if JAVA_SOURCE_MARKER in rel and rel.endswith(".java")
        ]
        other_java = [
            str(p.relative_to(repo))
            for p in _iter_repo_files(repo, "*.java")
            if JAVA_SOURCE_MARKER in str(p) and str(p.relative_to(repo)) not in changed_java
        ]
        for rel in changed_java + other_java:
            path = repo / rel
            if path.is_file():
                marker = "CHANGED IN THIS DIFF" if rel in changed_java else "unchanged"
                sources.append(f"// FILE ({marker}): {rel}\n{_read(path)}")

        for java in _iter_repo_files(repo, "*.java"):
            rel = str(java.relative_to(repo))
            if JAVA_TEST_MARKER not in rel:
                continue
            text = _read(java)
            patterns = extract_step_patterns(text)
            if patterns:
                step_patterns.extend(patterns)
                sources.append(f"// FILE (step definitions): {rel}\n{text}")
    else:
        # All .NET source files in the component, with changed ones first.
        changed_cs = [
            rel for rel in changed_files
            if rel.endswith(CS_SOURCE_EXT)
        ]
        other_cs = [
            str(p.relative_to(repo))
            for p in _iter_repo_files(repo, "*.cs")
            if "dotnet-component" in str(p.relative_to(repo)) and str(p.relative_to(repo)) not in changed_cs
        ]
        for rel in changed_cs + other_cs:
            path = repo / rel
            if path.is_file():
                marker = "CHANGED IN THIS DIFF" if rel in changed_cs else "unchanged"
                sources.append(f"// FILE ({marker}): {rel}\n{_read(path)}")

        for cs in _iter_repo_files(repo, "*StepDefinitions.cs"):
            rel = str(cs.relative_to(repo))
            text = _read(cs)
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
        "project_type": project_type,
    }


def _get_prompt_module(project_type: str):
    return dotnet_prompt if project_type == "dotnet" else __import__("testgen.prompts", fromlist=["*"])


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
                file_name=path, action=action.upper(), content=content,
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

    project_type = state.get("project_type", "java")
    prompt_module = _get_prompt_module(project_type)

    user_prompt = prompt_module.USER_PROMPT_TEMPLATE.format(
        target_component_context=state["target_component_context"],
        git_diff=state["git_diff"][:MAX_CONTEXT_CHARS],
        existing_feature_examples=state["existing_feature_examples"],
        api_spec=state["api_spec"],
    )

    if state.get("validation_errors"):
        errors = "\n".join(f"- {e}" for e in state["validation_errors"])
        user_prompt += prompt_module.RETRY_SUFFIX_TEMPLATE.format(errors=errors)

    if state.get("test_failures"):
        failures = "\n".join(state["test_failures"])
        user_prompt += prompt_module.TEST_FAILURE_TEMPLATE.format(failures=failures)

    full_prompt = f"""
    {prompt_module.SYSTEM_PROMPT}

    {user_prompt}

    {prompt_module.OUTPUT_FORMAT_INSTRUCTIONS}
    """

    response_text: Optional[str] = None
    last_error: Optional[Exception] = None

    # Validation-retry diversity: re-asking the same model after it failed
    # validation tends to reproduce the same misunderstanding. Rotate the chain
    # so later attempts start from a different model.
    rotation = state.get("attempts", 0) % len(MODELS)
    models = MODELS[rotation:] + MODELS[:rotation]

    rate_limit_models = set()  # Track which models hit rate limits

    # Outer loop: fall back across models. Inner loop: retry each model with
    # configurable backoff — free-pool 429s can last several minutes.
    for model in models:
        retries_left = MODEL_RETRIES
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
                rate_limit_models.discard(model)  # Clear rate limit if successful
            except Exception as e:
                last_error = e
                # Typed status from the SDK; substring checks on str(e) can
                # false-positive (digits appear in IDs and token counts).
                status = getattr(e, "status_code", None)
                if status == 429:
                    rate_limit_models.add(model)
                    logger.warning("[%s] RATE LIMIT (429) — all free models may be congested. "
                                 "Consider setting TESTGEN_MODEL to a paid model or your own key.", model)
                else:
                    logger.warning("[%s] failed (status=%s): %s", model, status, e)
                
                if status == 402:
                    raise RuntimeError("OpenRouter billing required") from e
                if status in (400, 404):
                    break  # bad request shape or model removed — next model
                
                retries_left -= 1
                if retries_left > 0:
                    retry_index = max(0, MODEL_RETRIES - retries_left - 1)
                    if retry_index >= len(BACKOFF_SCHEDULE):
                        sleep_time = BACKOFF_SCHEDULE[-1]
                    else:
                        sleep_time = BACKOFF_SCHEDULE[retry_index]
                    logger.info("Retrying in %ds... (retries_left=%d)", sleep_time, retries_left)
                    time.sleep(sleep_time)
        if response_text is not None:
            break

    if response_text is None:
        rate_limited_msg = ""
        if rate_limit_models:
            rate_limited_msg = (f"\n\n⚠️  RATE LIMIT ISSUE: All free models ({', '.join(rate_limit_models)}) "
                              f"are rate-limited.\n"
                              f"Solutions:\n"
                              f"  1. Set your own OpenRouter API key:\n"
                              f"     export OPENROUTER_API_KEY=sk-or-...\n"
                              f"  2. Use a paid model:\n"
                              f"     export TESTGEN_MODEL='anthropic/claude-3.5-sonnet'\n"
                              f"  3. Get free credits: https://openrouter.ai\n"
                              f"  4. Wait 30+ minutes and retry (rate limits reset)")
        raise RuntimeError(
            f"All models exhausted ({', '.join(MODELS)}). Last error: {last_error}{rate_limited_msg}"
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


def _infer_project_type_from_generation(generation: GenerationResult) -> str | None:
    for glue in generation.new_or_modified_step_definitions:
        if glue.file_name.endswith(".cs") or FEATURES_DIR_MARKER_DOTNET in glue.file_name:
            return "dotnet"
        if glue.file_name.endswith(".java") or FEATURES_DIR_MARKER in glue.file_name:
            return "java"
    for feature in generation.new_or_modified_features:
        # Check for correct dotnet path first
        if FEATURES_DIR_MARKER_DOTNET in feature.file_name:
            return "dotnet"
        # If feature is under dotnet-component/ but with wrong path, still dotnet
        if feature.file_name.startswith("dotnet-component/") and feature.file_name.endswith(".feature"):
            return "dotnet"
        # Check for java path
        if FEATURES_DIR_MARKER in feature.file_name:
            return "java"
    return None


def validate_output(state: TestGenState) -> TestGenState:
    """Validate generated Gherkin (structure, paths, CREATE/UPDATE consistency,
    and that every step matches an existing step definition)."""
    generation = state.get("generation")
    project_type = state.get("project_type", "java")
    git_diff = state.get("git_diff", "")
    
    # CRITICAL CHECK: If .NET source code changed but NO features generated, that's an ERROR
    if project_type == "dotnet":
        dotnet_files_changed = any(
            ".cs" in line or ".csproj" in line or "Program.cs" in line
            for line in git_diff.split("\n")
        )
        if dotnet_files_changed and (generation is None or not generation.new_or_modified_features):
            return {
                "validation_errors": [
                    "❌ CRITICAL VALIDATION FAILURE:\n"
                    ".NET source code changed (detected *.cs or *.csproj files in diff), "
                    "but ZERO feature files were generated.\n"
                    "The LLM MUST generate at least one SpecFlow feature file for every "
                    "new or modified .NET endpoint. \n"
                    "RETRY: Call the LLM again with stronger mandate to generate .NET tests."
                ]
            }
    
    if generation is None:
        # generate_tests already recorded parse errors; pass them through.
        return {}

    repo = Path(state["repo_path"]).resolve()
    step_patterns = state.get("step_patterns", [])
    errors: list = []
    seen_names = set()

    # Validate proposed glue first: its step patterns extend the set the
    # generated Gherkin is allowed to use.
    generated_patterns: list = []
    for glue in generation.new_or_modified_step_definitions:
        name = glue.file_name.lstrip("./")
        target = (repo / name).resolve()
        language = glue.language or ("java" if name.endswith(".java") else "csharp")

        if name in seen_names:
            errors.append(f"{name}: appears more than once in the output")
        seen_names.add(name)

        if project_type == "dotnet" and language == "java":
            errors.append(
                f"{name}: .java step-definition files are invalid for dotnet projects. "
                "Use a .cs file under dotnet-component/Tests/ instead."
            )
        elif language == "java":
            if not name.endswith(".java"):
                errors.append(f"{name}: Java step-definition file name must end with .java")
            if JAVA_TEST_MARKER not in name:
                errors.append(f"{name}: step definitions must live under {JAVA_TEST_MARKER}/")
        else:
            if not name.endswith(".cs"):
                errors.append(f"{name}: C# step-definition file name must end with .cs")
            if DOTNET_TESTS_DIR_MARKER not in name:
                errors.append(f"{name}: C# step definitions must live under {DOTNET_TESTS_DIR_MARKER}")
        if not target.is_relative_to(repo):
            errors.append(f"{name}: path escapes the repository root")

        patterns_in_file = extract_step_patterns(glue.content)
        if not patterns_in_file:
            errors.append(
                f"{name}: contains no [Given]/[When]/[Then] step definitions — "
                "if no new glue is needed, return an empty new_or_modified_step_definitions list. "
                "IF YOU INTRODUCED NEW STEPS in the feature file, this file MUST contain matching "
                "[Given], [When], [Then] method implementations for EVERY step used in the feature."
            )
        
        # For C# files, check for Java-style annotations (@Given, @When, @Then)
        if name.endswith(".cs"):
            java_matches = list(re.finditer(r'@(Given|When|Then|Before|After)\s*\([^)]*\)', glue.content))
            if java_matches:
                # Extract context around each match for clarity
                error_lines = []
                for match in java_matches[:3]:  # Show first 3 errors
                    start = max(0, match.start() - 50)
                    end = min(len(glue.content), match.end() + 50)
                    context = glue.content[start:end].replace('\n', ' ')
                    wrong = match.group(0)
                    right = f"[{match.group(1)}(...)]"
                    error_lines.append(f"  WRONG: {wrong}")
                    error_lines.append(f"  RIGHT: {right}")
                
                errors.append(
                    f"\n❌ {name}: CRITICAL - C# SpecFlow file MUST use [Given], [When], [Then] NOT @Given, @When, @Then\n"
                    + "\n".join(error_lines) + "\n"
                    f"SYNTAX RULES FOR C# SPECFLOW:\n"
                    f"  ✓ [Given(\"step text\")] — square brackets, NOT @ symbol\n"
                    f"  ✓ [When(\"step text\")]  — lowercase w after bracket\n"
                    f"  ✓ [Then(\"step text\")] — step text in quotes\n"
                    f"  ✓ public void MethodName() {{ }} — PascalCase method names\n"
                    f"  ✗ @Given, @When, @Then — Java syntax, CAUSES BUILD FAILURE\n"
                    f"  ✗ camelCase method names — use PascalCase\n"
                    f"\nREWRITE the entire C# file: replace ALL @Given with [Given], ALL @When with [When], ALL @Then with [Then]."
                )
        if target.is_file():
            removed = [
                p for p in extract_step_patterns(_read(target))
                if p not in patterns_in_file
            ]
            if removed:
                errors.append(
                    f"{name}: this rewrite drops existing step definition(s) "
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
        
        # Feature path validation: strict check for correct directory
        if project_type == "dotnet":
            if "dotnet-component/Tests/Features" not in name:
                errors.append(
                    f"{name}: .NET feature files MUST be under dotnet-component/Tests/Features/ "
                    f"not under {name.split('/')[0]}/. Use path: dotnet-component/Tests/Features/{name.split('/')[-1]}"
                )
        else:
            if "src/test/resources/features" not in name:
                errors.append(f"{name}: Java features must live under src/test/resources/features/")
        
        if not target.is_relative_to(repo):
            errors.append(f"{name}: path escapes the repository root")
        # No CREATE/UPDATE-vs-existence check: the model returns full feature
        # content either way, so the label is cosmetic — and rejecting on it made
        # the retry loop thrash once an earlier attempt had written the file.

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
                    "step definitions, or add the missing glue in a STEPDEF block under "
                    "dotnet-component/Tests/ if this is a dotnet project."
                )
                if "<" in step:
                    message += (
                        " Note: <name> placeholders are only substituted inside "
                        "Scenario Outlines that have a matching Examples column. "
                        "If this placeholder stands for a server-generated id, "
                        "you cannot know it — rewrite the step using the "
                        "'the last created <entity>' idiom (see the existing "
                        "steps) and make the glue track the id internally."
                    )
                errors.append(message)

    # Check for orphaned step definition files (created but empty)
    # If a step definition file was created, it MUST contain [Given]/[When]/[Then] methods
    feature_steps_used = set()
    for feature in generation.new_or_modified_features:
        for step in find_undefined_steps(feature.gherkin_content, []):
            feature_steps_used.add(step)
    
    if feature_steps_used:
        for glue in generation.new_or_modified_step_definitions:
            if not extract_step_patterns(glue.content):
                errors.append(
                    f"❌ {glue.file_name}: Step definition file was created but is EMPTY.\n"
                    f"The corresponding feature file uses custom steps that are NOT in existing bindings.\n"
                    f"This STEPDEF file MUST contain [Given], [When], [Then] methods matching these feature steps:\n"
                    f"  {chr(10).join(sorted(list(feature_steps_used)[:5]))}\n"
                    f"If there are more than 5 steps, implement all of them.\n"
                    f"RETRY: Return a complete C# step definition file with full method implementations."
                )

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
    outputs += [(g.file_name, g.action, g.content)
                for g in generation.new_or_modified_step_definitions]

    for file_name, _action, raw_content in outputs:
        target = repo / file_name.lstrip("./")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = raw_content.replace("\r\n", "\n")
        if not content.endswith("\n"):
            content += "\n"
        if target.is_file() and _read(target) == content:
            logger.info("UNCHANGED %s (generated content identical; skipping)", file_name)
            continue
        # Log the real action from disk state, not the model's (often wrong) label.
        action = "UPDATE" if target.is_file() else "CREATE"
        target.write_text(content, encoding="utf-8")
        written.append(str(target.relative_to(repo)))
        logger.info("%s %s", action, file_name)
    return {"written_files": written}


def _extract_compile_errors(mvn_output: str) -> list:
    """Pull Java compiler errors out of mvn output (build failed before tests)."""
    errors = []
    for line in mvn_output.splitlines():
        # e.g. "[ERROR] /path/Foo.java:[12,34] cannot find symbol"
        if ".java:[" in line and "ERROR" in line:
            errors.append(line.split("ERROR]", 1)[-1].strip())
    return errors[:25]


def _extract_scenario_failures(repo: Path) -> list:
    """Parse the Cucumber JSON report for failed scenarios + the reason."""
    report_path = repo / COMPONENT_DIR / "target" / "cucumber-report.json"
    if not report_path.is_file():
        return []
    try:
        report = json.loads(_read(report_path))
    except (ValueError, OSError):
        return []

    failures = []
    for feature in report:
        background = []
        for el in feature.get("elements", []):
            steps = el.get("steps", [])
            if el.get("type") == "background":
                background = steps
                continue
            for step in background + steps:
                res = step.get("result", {})
                if res.get("status") in ("failed", "undefined", "pending", "ambiguous"):
                    why = res.get("error_message", res.get("status", "")).splitlines()
                    failures.append(
                        f'- [{feature.get("name")}] "{el.get("name")}" → '
                        f'step "{step.get("keyword","").strip()} {step.get("name")}" '
                        f'{res.get("status")}: {why[0] if why else ""}'
                    )
                    break  # one failure per scenario is enough signal
    return failures


def _extract_dotnet_compile_errors(build_output: str) -> list:
    """Pull C# compiler errors out of dotnet build output."""
    errors = []
    for line in build_output.splitlines():
        # e.g. "path/File.cs(12,34): error CS0246: ..."
        if ".cs(" in line and ("error" in line.lower() or "warning" in line.lower()):
            errors.append(line.strip())
    return errors[:25]


def _extract_dotnet_test_failures(repo: Path) -> list:
    """Parse .NET TRX XML report for failed test results."""
    # Find the most recent TRX file
    test_results_dir = repo / "dotnet-component" / "TestResults"
    if not test_results_dir.exists():
        return []
    
    trx_files = sorted(test_results_dir.glob("**/*.trx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not trx_files:
        return []
    
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(str(trx_files[0]))
        root = tree.getroot()
        
        failures = []
        # TRX namespace
        ns = {'trx': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
        
        for result in root.findall('.//trx:UnitTestResult', ns):
            outcome = result.get('outcome', '')
            if outcome not in ('Failed', 'Error'):
                continue
            
            test_name = result.get('testName', 'Unknown')
            error_info = result.find('trx:Output/trx:ErrorInfo/trx:Message', ns)
            error_msg = error_info.text.strip() if error_info is not None and error_info.text else 'No details'
            
            failures.append(f"- {test_name}: {error_msg[:100]}")
        
        return failures[:25]
    except Exception as e:
        logger.warning("Failed to parse TRX file: %s", e)
        return []


def run_generated_tests(state: TestGenState) -> TestGenState:
    """Run tests for generated code; on failure, capture compile errors and test
    failures so the model can correct itself.

    For Java: runs `mvn test` on the java-component.
    For .NET: runs `dotnet test` on the BP.Tests.csproj project.
    
    Skips gracefully when tools aren't available or there's nothing to run."""
    repo = Path(state["repo_path"]).resolve()

    if not state.get("written_files"):
        return {"tests_passed": True, "test_failures": [],
                "test_report": "no files written; nothing to run"}

    project_type = state.get("project_type", "java")
    
    if project_type == "java":
        return _run_java_tests(repo, state)
    else:  # dotnet
        return _run_dotnet_tests(repo, state)


def _run_java_tests(repo: Path, state: TestGenState) -> TestGenState:
    """Execute Java tests via Maven."""
    if shutil.which(MVN) is None:
        logger.warning("'%s' not found on PATH — skipping test execution", MVN)
        return {"tests_passed": True, "test_failures": [],
                "test_report": "test execution skipped (Maven not available in this environment)"}

    pom = str(repo / COMPONENT_DIR / "pom.xml")
    logger.info("Running Java tests: %s -B -f %s test", MVN, pom)
    proc = subprocess.run(
        [MVN, "-B", "-f", pom, "test"],
        cwd=str(repo), capture_output=True, text=True, timeout=TEST_TIMEOUT,
    )

    if proc.returncode == 0:
        logger.info("Java tests passed.")
        return {"tests_passed": True, "test_failures": [],
                "test_report": "all Java tests passed"}

    test_attempts = state.get("test_attempts", 0) + 1
    output = proc.stdout + "\n" + proc.stderr

    compile_errors = _extract_compile_errors(output)
    scenario_failures = _extract_scenario_failures(repo)

    feedback: list = []
    if compile_errors:
        feedback.append("COMPILATION ERROR (the generated Java does not compile):")
        feedback += [f"- {e}" for e in compile_errors]
    if scenario_failures:
        feedback.append("SCENARIO FAILURES:")
        feedback += scenario_failures
    if not feedback:
        tail = "\n".join(output.splitlines()[-25:])
        feedback.append("`mvn test` failed; tail of the output:\n" + tail)

    logger.warning("Java test attempt %d failed (%d compile, %d scenario)",
                   test_attempts, len(compile_errors), len(scenario_failures))
    return {
        "tests_passed": False,
        "test_attempts": test_attempts,
        "test_failures": feedback,
        "test_report": f"{len(scenario_failures)} scenario failure(s), "
                       f"{len(compile_errors)} compile error(s) on attempt {test_attempts}",
        "validation_errors": [],
    }


def _run_dotnet_tests(repo: Path, state: TestGenState) -> TestGenState:
    """Execute .NET tests via dotnet test."""
    if shutil.which("dotnet") is None:
        logger.warning("'dotnet' not found on PATH — skipping test execution")
        return {"tests_passed": True, "test_failures": [],
                "test_report": "test execution skipped (dotnet CLI not available in this environment)"}

    project_file = str(repo / "dotnet-component" / "BP.Tests.csproj")
    logger.info("Running .NET tests: dotnet test %s", project_file)
    proc = subprocess.run(
        ["dotnet", "test", project_file, "--nologo", "--verbosity", "minimal", "--logger", "trx"],
        cwd=str(repo), capture_output=True, text=True, timeout=TEST_TIMEOUT,
    )

    if proc.returncode == 0:
        logger.info(".NET tests passed.")
        return {"tests_passed": True, "test_failures": [],
                "test_report": "all .NET tests passed"}

    test_attempts = state.get("test_attempts", 0) + 1
    output = proc.stdout + "\n" + proc.stderr

    compile_errors = _extract_dotnet_compile_errors(output)
    test_failures = _extract_dotnet_test_failures(repo)

    feedback: list = []
    if compile_errors:
        feedback.append("COMPILATION/BUILD ERROR (the generated C# does not compile):")
        feedback += [f"- {e}" for e in compile_errors]
    if test_failures:
        feedback.append("TEST FAILURES:")
        feedback += test_failures
    if not feedback:
        tail = "\n".join(output.splitlines()[-25:])
        feedback.append("`dotnet test` failed; tail of the output:\n" + tail)

    logger.warning(".NET test attempt %d failed (%d compile, %d failures)",
                   test_attempts, len(compile_errors), len(test_failures))
    return {
        "tests_passed": False,
        "test_attempts": test_attempts,
        "test_failures": feedback,
        "test_report": f"{len(test_failures)} test failure(s), "
                       f"{len(compile_errors)} compile error(s) on attempt {test_attempts}",
        "validation_errors": [],
    }



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

        tests_passed = state.get("tests_passed", True)
        if tests_passed:
            title = "test: update Cucumber regression suite for latest code changes"
            status = f"✅ Generated tests **passed** locally ({state.get('test_report','')})."
        else:
            title = "test: update Cucumber suite (⚠️ still failing — needs review)"
            failures = "\n".join(state.get("test_failures", []))
            status = (
                f"⚠️ Generated tests **still failing** after "
                f"{state.get('test_attempts', 0)} self-correction attempt(s). "
                "A human needs to resolve these — the most likely cause is the model "
                "asserting a wrong expected value, or the change being too large for "
                "one pass.\n\n<details><summary>Remaining failures</summary>\n\n"
                f"```\n{failures}\n```\n</details>"
            )

        body = (
            "## Auto-generated regression tests\n\n"
            f"{generation.analysis_summary}\n\n"
            f"### Test status\n{status}\n\n"
            f"### Impacted endpoints\n{endpoints}\n\n"
            f"### Files\n" + "\n".join(f"- `{f}`" for f in state["written_files"]) + "\n\n"
            "Please review the scenarios before merging. Regression runs automatically "
            "after merge.\n\n"
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
        )
        pr_url = _run(
            ["gh", "pr", "create", "--title", title, "--body", body, "--head", branch, "--base", original_ref],
            cwd=repo,
        ).strip()
        logger.info("Opened PR: %s", pr_url)
        return {"pr_url": pr_url}
    finally:
        # Best-effort return to where we started (matters for local runs;
        # harmless in CI). "HEAD" means we began detached — stay put then.
        if original_ref != "HEAD":
            subprocess.run(["git", "checkout", original_ref], cwd=repo, capture_output=True)