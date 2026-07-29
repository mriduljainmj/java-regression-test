"""LangGraph nodes for the Cucumber regression test-generation pipeline."""

from __future__ import annotations

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

from .ado import extract_work_item_id, fetch_work_item_context
from .criticality import load_criticality, touched_controllers
from .gherkin import extract_step_patterns, extract_step_patterns_js, find_undefined_steps
from .prompts import (
    OUTPUT_FORMAT_INSTRUCTIONS,
    RETRY_SUFFIX_TEMPLATE,
    SYSTEM_PROMPT,
    TEST_FAILURE_TEMPLATE,
    USER_PROMPT_TEMPLATE,
)
from . import dotnet_prompt
from . import ui_prompt
from .state import FeatureFile, GenerationResult, StepDefinitionFile, TestGenState

logger = logging.getLogger(__name__)

_FORCED_PROJECT_TYPE = os.environ.get("TESTGEN_FORCE_PROJECT_TYPE", "").strip().lower()
if _FORCED_PROJECT_TYPE and _FORCED_PROJECT_TYPE not in {"java", "dotnet", "ui"}:
    logger.warning(
        "Ignoring invalid TESTGEN_FORCE_PROJECT_TYPE=%r (expected 'java', 'dotnet', or 'ui')",
        _FORCED_PROJECT_TYPE,
    )
    _FORCED_PROJECT_TYPE = ""

# Safety cap on total model calls (structural retries + rotation). Set high
# enough that the execution-feedback rounds below never trip it.
# Increased to 12 for C# syntax correction retries (6 is insufficient for @Given → [Given] fixes)
MAX_ATTEMPTS = int(os.environ.get("TESTGEN_MAX_ATTEMPTS", "3"))

# Execution-feedback loop: run the generated tests and feed failures back to the
# model, at most this many times (the user-facing "max 3 retries").
MAX_TEST_ATTEMPTS = int(os.environ.get("TESTGEN_MAX_TEST_ATTEMPTS", "3"))

# Maven command + the component to test. Override MAVEN_CMD if mvn isn't on PATH.
MVN = os.environ.get("MAVEN_CMD", "mvn")
COMPONENT_DIR = os.environ.get("TESTGEN_COMPONENT_DIR", "java-component")
TEST_TIMEOUT = int(os.environ.get("TESTGEN_TEST_TIMEOUT", "900"))

# Per-section guardrail for very large diffs/sources.
MAX_CONTEXT_CHARS = int(os.environ.get("TESTGEN_MAX_CONTEXT_CHARS", "60000"))

# Optional human guidance is read from this file at the repo root (edit it to tell
# the agent which edge cases to cover). Empty / comments-only means "no guidance".
GUIDANCE_FILE = "testgen-guidance.md"

# .NET context shaping: changed files first, then high-signal files only.
DOTNET_MAX_SOURCE_FILES = int(os.environ.get("TESTGEN_DOTNET_MAX_SOURCE_FILES", "24"))
DOTNET_MAX_FILE_CHARS = int(os.environ.get("TESTGEN_DOTNET_MAX_FILE_CHARS", "8000"))
DOTNET_MAX_FEATURE_EXAMPLES = int(os.environ.get("TESTGEN_DOTNET_MAX_FEATURE_EXAMPLES", "30000"))

# Per-model retry tuning for transient OpenRouter rate limits.
MODEL_RETRIES = int(os.environ.get("TESTGEN_MODEL_RETRIES", "3"))
BACKOFF_SCHEDULE = [
    int(v.strip())
    for v in os.environ.get("TESTGEN_BACKOFF_SECONDS", "20,45,90").split(",")
    if v.strip()
]

# Model selection: use explicit TESTGEN_MODELS when provided, otherwise keep the
# existing free-pool fallback chain with TESTGEN_MODEL as first preference.
if os.environ.get("TESTGEN_MODELS"):
    MODELS = [m.strip() for m in os.environ["TESTGEN_MODELS"].split(",") if m.strip()]
else:
    MODELS = [
        os.environ.get("TESTGEN_MODEL", "openai/gpt-oss-120b:free"),
        "openai/gpt-oss-20b:free",
        "google/gemma-4-26b-a4b-it:free",
    ]

# Java paths are scoped to COMPONENT_DIR (not bare "src/main/java" anywhere in the
# repo) so this agent can be dropped into a real repo that has other, unrelated
# Java code alongside the component it should actually test. Each is still
# individually overridable for repos that don't follow the Maven convention.
JAVA_SOURCE_MARKER = os.environ.get("TESTGEN_JAVA_SOURCE_MARKER", f"{COMPONENT_DIR}/src/main/java")
JAVA_TEST_MARKER = os.environ.get("TESTGEN_JAVA_TEST_MARKER", f"{COMPONENT_DIR}/src/test/java")
FEATURES_DIR_MARKER = os.environ.get(
    "TESTGEN_JAVA_FEATURES_DIR", f"{COMPONENT_DIR}/src/test/resources/features"
)

# .NET support — same portability contract as Java/UI: a single component-dir env
# var (default matches this demo repo's layout) plus an override for the specific
# test project file, since a real .NET solution's test project is rarely named
# BP.Tests.csproj.
CS_SOURCE_EXT = ".cs"
DOTNET_COMPONENT_DIR = os.environ.get("TESTGEN_DOTNET_COMPONENT_DIR", "dotnet-component")
DOTNET_TEST_PROJECT = os.environ.get("TESTGEN_DOTNET_TEST_PROJECT", "BP.Tests.csproj")
FEATURES_DIR_MARKER_DOTNET = os.environ.get(
    "TESTGEN_DOTNET_FEATURES_DIR", f"{DOTNET_COMPONENT_DIR}/Tests/Features"
)
DOTNET_TESTS_DIR_MARKER = os.environ.get(
    "TESTGEN_DOTNET_TESTS_DIR", f"{DOTNET_COMPONENT_DIR}/Tests/"
)

# Front-end UI support (Playwright + Cucumber-JS). Framework-agnostic: the tests
# drive the rendered DOM, so React/Vue/Svelte/plain HTML all route here. Markers
# derive from UI_COMPONENT_DIR (same portability contract as Java/.NET above),
# each still individually overridable for a layout that doesn't follow the
# component/src, component/tests/, component/tests/features convention.
UI_COMPONENT_DIR = os.environ.get("TESTGEN_UI_COMPONENT_DIR", "frontend-react")
UI_SOURCE_MARKER = os.environ.get("TESTGEN_UI_SOURCE_MARKER", f"{UI_COMPONENT_DIR}/src")
UI_TESTS_DIR_MARKER = os.environ.get("TESTGEN_UI_TESTS_DIR", f"{UI_COMPONENT_DIR}/tests/")
UI_FEATURES_DIR_MARKER = os.environ.get("TESTGEN_UI_FEATURES_DIR", f"{UI_COMPONENT_DIR}/tests/features")
UI_SOURCE_EXTS = (".jsx", ".tsx", ".vue", ".svelte", ".js", ".ts")

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


def _truncate_file_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n// ...truncated for prompt budget...\n"


def _dotnet_relevance_score(rel_path: str) -> int:
    rel = rel_path.lower()
    score = 0
    if rel.endswith("program.cs"):
        score += 120
    if "controller" in rel or "/controllers/" in rel:
        score += 100
    if "service" in rel or "/services/" in rel:
        score += 80
    if "/models/" in rel or "dto" in rel:
        score += 60
    if rel.endswith("stepdefinitions.cs"):
        score += 40
    if rel.endswith(".csproj"):
        score += 20
    return score


def _select_dotnet_context_files(repo: Path, changed_files: list[str]) -> list[str]:
    changed_cs = [
        rel for rel in changed_files
        if rel.startswith(f"{DOTNET_COMPONENT_DIR}/") and rel.endswith(CS_SOURCE_EXT)
    ]
    all_component_cs = [
        str(p.relative_to(repo))
        for p in _iter_repo_files(repo, "*.cs")
        if str(p.relative_to(repo)).startswith(f"{DOTNET_COMPONENT_DIR}/")
    ]

    unchanged_cs = [p for p in all_component_cs if p not in changed_cs]
    unchanged_cs.sort(key=lambda rel: (_dotnet_relevance_score(rel) * -1, rel))

    selected = list(changed_cs)
    for rel in unchanged_cs:
        if len(selected) >= DOTNET_MAX_SOURCE_FILES:
            break
        selected.append(rel)
    return selected


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
    # Front-end source changes (not the UI tests themselves).
    ui_changes = [
        f for f in changed_files
        if f.startswith(UI_SOURCE_MARKER)
        and f.endswith(UI_SOURCE_EXTS)
        and UI_TESTS_DIR_MARKER not in f
    ]

    if _FORCED_PROJECT_TYPE:
        project_type = _FORCED_PROJECT_TYPE
    else:
        project_type = None
        if cs_changes:
            project_type = "dotnet"
        elif java_changes:
            project_type = "java"
        elif ui_changes:
            project_type = "ui"

    logger.info(
        "Change detection summary: total=%d, java=%d, dotnet=%d, ui=%d, selected=%s, forced=%s",
        len(changed_files),
        len(java_changes),
        len(cs_changes),
        len(ui_changes),
        project_type or "none",
        _FORCED_PROJECT_TYPE or "none",
    )
    if changed_files:
        logger.info("Changed files (first 25): %s", ", ".join(changed_files[:25]))

    update: TestGenState = {"git_diff": diff, "changed_files": changed_files, "resolved_base": base}
    if project_type is None:
        update["skipped_reason"] = (
            "No Java, C#, or front-end source changes between "
            f"{base} and {head}; nothing to generate tests for."
        )
        return update

    # Criticality skip (QA-owned, in PROJECT.md): if EVERY controller touched by this
    # change is set to a skipped criticality, don't generate tests for it.
    crit_map, skip_levels = load_criticality(Path(repo))
    touched = touched_controllers(changed_files)
    if skip_levels and touched and all(crit_map.get(c, "MEDIUM") in skip_levels for c in touched):
        levels = ", ".join(sorted(skip_levels))
        detail = ", ".join(f"{c}={crit_map.get(c, 'MEDIUM')}" for c in touched)
        logger.info("Skipping generation — changed controller(s) [%s] are in skipped criticality (%s)",
                    detail, levels)
        update["skipped_reason"] = (
            f"Changed controller(s) {detail} are set to a skipped criticality ({levels}) "
            "in PROJECT.md — test generation skipped."
        )
        return update

    update["project_type"] = project_type
    return update


def _read_guidance_file(repo: Path) -> str:
    """Read optional human guidance from testgen-guidance.md at the repo root.

    HTML comment blocks (the usage instructions shipped in the file) are stripped,
    so a file that still only contains the template counts as 'no guidance'.
    """
    path = repo / GUIDANCE_FILE
    if not path.is_file():
        return ""
    try:
        text = path.read_text(errors="ignore")
    except Exception:
        return ""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)  # drop instruction comments
    return text.strip()


def gather_context(state: TestGenState) -> TestGenState:
    """Read source files, glue code, existing features, and any API spec."""
    repo = Path(state["repo_path"])
    changed_files = state["changed_files"]
    project_type = state.get("project_type", "java")

    sources: list = []
    step_patterns: list = []

    ado_work_item_id = state.get("ado_work_item_id") or os.environ.get("AZDO_WORK_ITEM_ID", "")
    if not ado_work_item_id:
        commit_messages = ""
        resolved_base = state.get("resolved_base") or state["base_ref"]
        try:
            commit_messages = _run(
                ["git", "log", "--format=%B", f"{resolved_base}..{state['head_ref']}"],
                cwd=str(repo),
            )
        except Exception:
            commit_messages = ""
        ado_work_item_id = extract_work_item_id(commit_messages) or ""

    if ado_work_item_id:
        logger.info("ADO work item detected: %s", ado_work_item_id)
    else:
        logger.info("No ADO work item detected from state/env/commit range")

    ado_org_url = state.get("ado_org_url") or os.environ.get("AZDO_ORG_URL", "")
    ado_project = state.get("ado_project") or os.environ.get("AZDO_PROJECT", "")
    ado_pat = os.environ.get("AZDO_PAT", "")
    ado_work_item_context = "Not available."
    if ado_work_item_id:
        ado_work_item_context = fetch_work_item_context(
            org_url=ado_org_url,
            project=ado_project,
            pat=ado_pat,
            work_item_id=ado_work_item_id,
        )
        if ado_work_item_context.startswith("Detected Azure DevOps work item"):
            logger.warning("ADO context fetch issue: %s", ado_work_item_context)
        elif ado_work_item_context == "Not available.":
            logger.warning(
                "ADO context not available. Check AZDO_ORG_URL, AZDO_PROJECT, AZDO_PAT, and work item id"
            )
        else:
            has_description = "Description: (missing)" not in ado_work_item_context and "Description:" in ado_work_item_context
            has_acceptance = (
                "Acceptance Criteria: (missing)" not in ado_work_item_context
                and "Acceptance Criteria:" in ado_work_item_context
            )
            preview = ado_work_item_context[:400].replace("\n", " | ")
            logger.info(
                "ADO context fetched for work item %s (len=%d, hasDescription=%s, hasAcceptance=%s): %s",
                ado_work_item_id,
                len(ado_work_item_context),
                has_description,
                has_acceptance,
                preview,
            )
    else:
        ado_work_item_context = (
            "No Azure DevOps work item id was detected. "
            "Use AB#1234 / ADO-1234 in the commit or set AZDO_WORK_ITEM_ID to enrich the prompt."
        )

    # Optional free-text guidance from a human: specific edge cases / scenarios the
    # generated tests must cover. Comes from the CLI (--guidance) or, preferably, the
    # testgen-guidance.md file at the repo root (the label-refine flow writes the QA
    # comment into that file before running).
    reviewer_guidance = (state.get("reviewer_guidance") or _read_guidance_file(repo)).strip()
    if reviewer_guidance:
        logger.info("Reviewer guidance provided (%d chars) — model must cover the named edge cases", len(reviewer_guidance))
    else:
        reviewer_guidance = (
            "No specific guidance provided. Use your judgment to cover boundary values, "
            "invalid inputs, and error paths for the changed behavior."
        )

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
    elif project_type == "ui":
        # Front-end source (changed files first), plus existing JS step definitions
        # so the model can reuse step wording. Framework-agnostic — the source may
        # be JSX, Vue, Svelte, or plain JS/TS.
        changed_ui = [
            rel for rel in changed_files
            if rel.startswith(UI_SOURCE_MARKER) and rel.endswith(UI_SOURCE_EXTS)
        ]
        seen = set(changed_ui)
        other_ui: list = []
        for ext in UI_SOURCE_EXTS:
            for p in _iter_repo_files(repo, f"*{ext}"):
                rel = str(p.relative_to(repo))
                if rel.startswith(UI_SOURCE_MARKER) and rel not in seen:
                    seen.add(rel)
                    other_ui.append(rel)
        for rel in changed_ui + other_ui:
            path = repo / rel
            if path.is_file():
                marker = "CHANGED IN THIS DIFF" if rel in changed_ui else "unchanged"
                sources.append(
                    f"// FILE ({marker}): {rel}\n"
                    f"{_truncate_file_text(_read(path), DOTNET_MAX_FILE_CHARS)}"
                )

        for js in _iter_repo_files(repo, "*.steps.js"):
            rel = str(js.relative_to(repo))
            if not rel.startswith(UI_TESTS_DIR_MARKER):
                continue
            text = _read(js)
            patterns = extract_step_patterns_js(text)
            if patterns:
                step_patterns.extend(patterns)
            sources.append(
                f"// FILE (step definitions): {rel}\n"
                f"{_truncate_file_text(text, DOTNET_MAX_FILE_CHARS)}"
            )
    else:
        selected_cs = _select_dotnet_context_files(repo, changed_files)
        changed_cs_set = {
            rel for rel in changed_files
            if rel.startswith(f"{DOTNET_COMPONENT_DIR}/") and rel.endswith(CS_SOURCE_EXT)
        }
        for rel in selected_cs:
            path = repo / rel
            if path.is_file():
                marker = "CHANGED IN THIS DIFF" if rel in changed_cs_set else "unchanged"
                sources.append(
                    f"// FILE ({marker}): {rel}\n"
                    f"{_truncate_file_text(_read(path), DOTNET_MAX_FILE_CHARS)}"
                )

        for cs in _iter_repo_files(repo, "*StepDefinitions.cs"):
            rel = str(cs.relative_to(repo))
            if not rel.startswith(DOTNET_TESTS_DIR_MARKER):
                continue
            text = _read(cs)
            patterns = extract_step_patterns(text)
            if patterns:
                step_patterns.extend(patterns)
            sources.append(
                f"// FILE (step definitions): {rel}\n"
                f"{_truncate_file_text(text, DOTNET_MAX_FILE_CHARS)}"
            )
    if not step_patterns:
        logger.warning("no step definitions found — undefined-step validation disabled")

    features: list = []
    for feature in _iter_repo_files(repo, "*.feature"):
        rel = str(feature.relative_to(repo))
        if project_type == "dotnet" and not rel.startswith(f"{FEATURES_DIR_MARKER_DOTNET}/"):
            continue
        if project_type == "java" and FEATURES_DIR_MARKER not in rel:
            continue
        if project_type == "ui" and not rel.startswith(UI_FEATURES_DIR_MARKER):
            continue
        features.append(f"# FILE: {rel}\n{_read(feature)}")

    feature_examples = "\n\n".join(features)
    if project_type == "dotnet":
        feature_examples = feature_examples[:DOTNET_MAX_FEATURE_EXAMPLES]
    else:
        feature_examples = feature_examples[:MAX_CONTEXT_CHARS]

    api_spec = ""
    for candidate in ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml", "swagger.json"):
        matches = list(_iter_repo_files(repo, candidate))
        if matches:
            api_spec = _read(matches[0])
            break

    return {
        "target_component_context": "\n\n".join(sources)[:MAX_CONTEXT_CHARS],
        "existing_feature_examples": feature_examples,
        "api_spec": api_spec[:MAX_CONTEXT_CHARS] or "Not available.",
        "ado_work_item_id": ado_work_item_id,
        "ado_work_item_context": ado_work_item_context[:MAX_CONTEXT_CHARS],
        "reviewer_guidance": reviewer_guidance[:MAX_CONTEXT_CHARS],
        "step_patterns": step_patterns,
        "attempts": 0,
        "validation_errors": [],
        "project_type": project_type,
    }


def _get_prompt_module(project_type: str):
    if project_type == "dotnet":
        return dotnet_prompt
    if project_type == "ui":
        return ui_prompt
    return __import__("testgen.prompts", fromlist=["*"])


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
    # A pure path/route rename only needs the URL strings in the glue changed. Do that
    # deterministically instead of asking a model to rewrite a whole step-def file —
    # which is how free models introduce compile errors. The LLM still handles
    # everything else (new endpoints, validation, renames bundled with logic changes).
    if _pure_route_rename(state.get("git_diff", "")):
        det = _deterministic_rename_generation(state)
        if det is not None:
            logger.info(
                "Pure path rename — patched %d glue file(s) deterministically, skipping the LLM",
                len(det.new_or_modified_step_definitions),
            )
            return {"generation": det, "attempts": state.get("attempts", 0) + 1,
                    "validation_errors": []}

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
        ado_work_item_context=state.get("ado_work_item_context", "Not available."),
        reviewer_guidance=state.get("reviewer_guidance", "No specific guidance provided."),
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

    rate_limit_models = set()  # models that returned 429 at least once
    dead_models = set()        # 400/404 — unusable shape/removed, drop from rotation

    # Try EVERY model each round before sleeping: a 429 on one model must fall
    # straight through to the next, not abort the run. Only when a whole pass over
    # all models finds nothing usable do we back off and retry the set — up to
    # MODEL_RETRIES rounds.
    for round_index in range(MODEL_RETRIES):
        saw_transient = False
        for model in MODELS:
            if model in dead_models:
                continue
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
                rate_limit_models.discard(model)  # clear if it recovered
                logger.info("Generated with model %s", model)
                break
            except Exception as e:
                last_error = e
                # Typed status from the SDK; substring checks on str(e) can
                # false-positive (digits appear in IDs and token counts).
                status = getattr(e, "status_code", None)
                if status == 402:
                    raise RuntimeError("OpenRouter billing required") from e
                if status in (400, 404):
                    logger.warning("[%s] unusable (status=%s) — dropping from rotation", model, status)
                    dead_models.add(model)
                    continue
                if status == 429:
                    rate_limit_models.add(model)
                    logger.warning("[%s] rate limited (429) — falling through to next model", model)
                else:
                    logger.warning("[%s] failed (status=%s): %s", model, status, e)
                saw_transient = True
                continue

        if response_text is not None:
            break
        if not saw_transient:
            break  # every model returned a hard 4xx — backing off won't help
        if round_index < MODEL_RETRIES - 1:
            sleep_time = BACKOFF_SCHEDULE[min(round_index, len(BACKOFF_SCHEDULE) - 1)]
            logger.info(
                "All models unavailable this pass; backing off %ds before round %d/%d",
                sleep_time, round_index + 2, MODEL_RETRIES,
            )
            time.sleep(sleep_time)

    if response_text is None:
        rate_limited_msg = ""
        if rate_limit_models:
            rate_limited_msg = (
                f"\n\n⚠️  RATE LIMIT: these models returned 429 ({', '.join(sorted(rate_limit_models))}).\n"
                f"The free OpenRouter pool is saturated. Options:\n"
                f"  1. Set TESTGEN_MODEL to a funded/stronger model\n"
                f"  2. Use a funded OpenRouter key (https://openrouter.ai/settings/integrations)\n"
                f"  3. Re-run the workflow after the provider cools down"
            )
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


_ROUTE_ANNOTATION_RE = re.compile(
    r'(?:Mapping|\[Route|\[Http[A-Za-z]*)\s*\(\s*(?:value\s*=\s*)?"([^"]+)"'
)


def _diff_renames_route(git_diff: str) -> bool:
    """True when the diff changes a controller route/path string — a Java @*Mapping
    or a .NET [Route]/[Http*] value that was removed and re-added differently. Such a
    rename must be reflected in the step-definition glue that builds the URLs."""
    removed, added = [], []
    for line in git_diff.splitlines():
        if line.startswith("-") and not line.startswith("---"):
            removed += _ROUTE_ANNOTATION_RE.findall(line)
        elif line.startswith("+") and not line.startswith("+++"):
            added += _ROUTE_ANNOTATION_RE.findall(line)
    return bool(removed) and bool(added) and set(removed) != set(added)


def _rename_pairs(git_diff: str):
    """Extract (old_path, new_path) route-rename pairs from the diff."""
    removed, added = [], []
    for line in git_diff.splitlines():
        if line.startswith("-") and not line.startswith("---"):
            removed += _ROUTE_ANNOTATION_RE.findall(line)
        elif line.startswith("+") and not line.startswith("+++"):
            added += _ROUTE_ANNOTATION_RE.findall(line)
    old_only = [r for r in removed if r not in added]
    new_only = [a for a in added if a not in removed]
    return list(zip(old_only, new_only))


def _apply_path_rename(text: str, old_full: str, new_full: str) -> str:
    """Boundary-safe replacement of a renamed route. Replaces the differing trailing
    segment so a RestAssured basePath-split glue (basePath '/api/v1' + '.get(/orders)')
    is patched too, and the (?![A-Za-z0-9]) guard avoids partial hits (/orders vs
    /orderss). Only URL strings change — nothing else in the file is touched."""
    o = old_full.strip("/").split("/")
    n = new_full.strip("/").split("/")
    i = 0
    while i < len(o) and i < len(n) and o[i] == n[i]:
        i += 1
    if i >= len(o):
        return text
    old_suffix = "/" + "/".join(o[i:])
    new_suffix = "/" + "/".join(n[i:]) if i < len(n) else ""
    return re.sub(re.escape(old_suffix) + r"(?![A-Za-z0-9])", new_suffix, text)


def _pure_route_rename(git_diff: str) -> bool:
    """True when the ONLY component-source change is the route string(s) — a pure
    rename with no logic change, safe to patch deterministically. Changes to the
    agent's own code, tests, or other files are ignored for this check."""
    if not _rename_pairs(git_diff):
        return False
    cur = None
    for line in git_diff.splitlines():
        if line.startswith("+++ "):
            cur = line[4:].strip()
            continue
        if line.startswith("--- ") or not (line.startswith("+") or line.startswith("-")):
            continue
        is_component_src = bool(cur) and (
            (f"{COMPONENT_DIR}/src/main" in cur or (DOTNET_COMPONENT_DIR in cur and "/Tests/" not in cur))
            and cur.endswith((".java", ".cs"))
        )
        if not is_component_src:
            continue
        body = line[1:].strip()
        if not body or body in ("{", "}", ");", ")", ";"):
            continue
        if _ROUTE_ANNOTATION_RE.search(body):
            continue
        return False  # a real logic change in the controller — let the LLM handle it
    return True


def _deterministic_rename_generation(state: TestGenState):
    """For a pure path rename, patch the step-definition glue directly — only the URL
    strings, so it always compiles — instead of asking a model to rewrite the whole
    file. Returns a GenerationResult, or None if no glue references the renamed path."""
    pairs = _rename_pairs(state.get("git_diff", ""))
    if not pairs:
        return None
    repo = Path(state["repo_path"])
    project_type = state.get("project_type", "java")

    glue_paths = []
    if project_type == "dotnet":
        for cs in _iter_repo_files(repo, "*StepDefinitions.cs"):
            if str(cs.relative_to(repo)).startswith(DOTNET_TESTS_DIR_MARKER):
                glue_paths.append(cs)
    else:
        for j in _iter_repo_files(repo, "*.java"):
            rel = str(j.relative_to(repo))
            if JAVA_TEST_MARKER in rel and extract_step_patterns(_read(j)):
                glue_paths.append(j)

    changed = []
    for p in glue_paths:
        text = _read(p)
        new = text
        for old_full, new_full in pairs:
            new = _apply_path_rename(new, old_full, new_full)
        if new != text:
            rel = str(p.relative_to(repo))
            changed.append(StepDefinitionFile(
                file_name=rel, action="UPDATE", content=new,
                language="csharp" if rel.endswith(".cs") else "java"))

    if not changed:
        return None
    renames = ", ".join(f"{o} -> {n}" for o, n in pairs)
    return GenerationResult(
        impacted_endpoints=[f"path renamed: {o} -> {n}" for o, n in pairs],
        analysis_summary=(
            f"Pure path rename ({renames}). Patched the request URLs in the step "
            "definitions deterministically; no scenario or assertion was changed."),
        new_or_modified_features=[],
        new_or_modified_step_definitions=changed,
    )


def _glue_language(name: str, language: Optional[str]) -> str:
    """Resolve a step-definition file's language from its hint or extension."""
    if language:
        return language
    if name.endswith(".js") or name.endswith(".ts"):
        return "javascript"
    if name.endswith(".java"):
        return "java"
    return "csharp"


def _glue_patterns(name: str, content: str, language: Optional[str] = None) -> list:
    """Extract step patterns from glue with the right parser for its language."""
    if _glue_language(name, language) == "javascript":
        return extract_step_patterns_js(content)
    return extract_step_patterns(content)


def validate_output(state: TestGenState) -> TestGenState:
    """Validate generated Gherkin (structure, paths, CREATE/UPDATE consistency,
    and that every step matches an existing step definition)."""
    generation = state.get("generation")
    project_type = state.get("project_type", "java")
    git_diff = state.get("git_diff", "")

    # Route/path RENAME but an EMPTY generation: the model typically explains in its
    # analysis that "the step definitions must be updated" and then forgets to emit
    # the glue block — leaving nothing to write and no PR. URLs live in the step
    # definitions, not the .feature files, so force the model to actually produce the
    # updated glue. Applies to Java and .NET.
    empty_generation = generation is not None and (
        not generation.new_or_modified_features
        and not generation.new_or_modified_step_definitions
    )
    if empty_generation and _diff_renames_route(git_diff):
        glue_hint = ("*StepDefinitions.cs" if project_type == "dotnet"
                     else "*StepDefinitions.java / *Steps.java")
        return {
            "validation_errors": [
                "A controller route/path was RENAMED in the diff, but you produced NO "
                "step-definition update and NO feature file. The request URLs are built "
                "in the STEP DEFINITIONS (RestAssured basePath + \".get(/orders)\" for "
                "Java, HttpClient paths for .NET), NOT in the .feature files. Return the "
                f"FULL updated content of the affected step-definition file(s) ({glue_hint}) "
                "as UPDATE blocks — change the old path to the new one and preserve every "
                "existing step. Do NOT answer with analysis only."
            ]
        }

    # CRITICAL CHECK: If .NET source code changed but NO features generated, that's an ERROR
    if project_type == "dotnet":
        dotnet_files_changed = any(
            ".cs" in line or ".csproj" in line or "Program.cs" in line
            for line in git_diff.split("\n")
        )
        # A pure path/route rename is fixed by updating step definitions (which build
        # the URLs) with NO feature change — so only error when there is neither a
        # feature nor a step-definition update to show for a .NET source change.
        produced_nothing = generation is None or (
            not generation.new_or_modified_features
            and not generation.new_or_modified_step_definitions
        )
        if dotnet_files_changed and produced_nothing:
            return {
                "validation_errors": [
                    "❌ CRITICAL VALIDATION FAILURE:\n"
                    ".NET source code changed (detected *.cs or *.csproj files in diff), "
                    "but ZERO feature files AND ZERO step-definition updates were generated.\n"
                    "For a NEW or MODIFIED endpoint, generate a SpecFlow feature file. "
                    "For a pure path/route RENAME, return the updated step-definition "
                    "file(s) with the new URL instead.\n"
                    "RETRY: Call the LLM again with a stronger mandate."
                ]
            }

    # CRITICAL CHECK: If front-end source changed but NO features generated, that's
    # an ERROR — parity with the .NET guard above. Without this, a model that wrongly
    # decides a UI change (or a whole new page) is "not observable" is never forced
    # to retry, unlike the other two project types.
    if project_type == "ui":
        ui_files_changed = any(
            f.startswith(UI_SOURCE_MARKER) and f.endswith(UI_SOURCE_EXTS) and UI_TESTS_DIR_MARKER not in f
            for f in state.get("changed_files", [])
        )
        produced_nothing = generation is None or (
            not generation.new_or_modified_features
            and not generation.new_or_modified_step_definitions
        )
        if ui_files_changed and produced_nothing:
            return {
                "validation_errors": [
                    "❌ CRITICAL VALIDATION FAILURE:\n"
                    f"Front-end source changed under {UI_SOURCE_MARKER}/, but ZERO feature "
                    "files AND ZERO step-definition updates were generated.\n"
                    "A new/changed on-screen message, field, validation rule, or page is "
                    "observable and REQUIRES a Cucumber feature file. Only a change with "
                    "genuinely no visible/textual effect (pure internal refactor, styling-only "
                    "change with no rendered difference) may produce nothing — if that is truly "
                    "the case here, state so explicitly in ANALYSIS instead of returning empty.\n"
                    "RETRY: Call the LLM again with a stronger mandate."
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
        language = _glue_language(name, glue.language)

        if name in seen_names:
            errors.append(f"{name}: appears more than once in the output")
        seen_names.add(name)

        if project_type == "ui":
            if not name.endswith(".js"):
                errors.append(f"{name}: UI step-definition file name must end with .js (Playwright/Cucumber-JS)")
            if UI_TESTS_DIR_MARKER not in name:
                errors.append(f"{name}: UI step definitions must live under {UI_TESTS_DIR_MARKER}")
        elif project_type == "dotnet" and language == "java":
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

        patterns_in_file = _glue_patterns(name, glue.content, glue.language)
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
                p for p in _glue_patterns(name, _read(target), glue.language)
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
        
        # Enforce the detected project_type: a run must NOT emit paths for the
        # other component. This is what stopped a .NET change from producing a
        # java-component feature (and then running mvn) in earlier runs.
        if project_type == "dotnet":
            if FEATURES_DIR_MARKER_DOTNET not in name:
                errors.append(
                    f"{name}: this is a .NET run — feature files MUST be under "
                    f"{FEATURES_DIR_MARKER_DOTNET}/. Do NOT write to {COMPONENT_DIR}/ "
                    f"or any other project. Regenerate at "
                    f"{FEATURES_DIR_MARKER_DOTNET}/{name.split('/')[-1]}"
                )
        elif project_type == "ui":
            if not name.startswith(UI_FEATURES_DIR_MARKER):
                errors.append(
                    f"{name}: this is a UI run — feature files MUST be under "
                    f"{UI_FEATURES_DIR_MARKER}/ (not under {COMPONENT_DIR}/ or {DOTNET_COMPONENT_DIR}/). "
                    f"Regenerate at {UI_FEATURES_DIR_MARKER}/{name.split('/')[-1]}"
                )
        else:  # java
            if FEATURES_DIR_MARKER not in name:
                errors.append(
                    f"{name}: this is a Java run — features must live under "
                    f"{FEATURES_DIR_MARKER}/ (not under {DOTNET_COMPONENT_DIR}/)."
                )
        
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
            if project_type == "dotnet":
                glue_loc = f"{DOTNET_TESTS_DIR_MARKER}StepDefinitions/"
            elif project_type == "ui":
                glue_loc = f"{UI_TESTS_DIR_MARKER}steps/"
            else:
                glue_loc = f"{JAVA_TEST_MARKER}/.../cucumber/"
            for step in find_undefined_steps(feature.gherkin_content, all_patterns):
                message = (
                    f'{name}: step "{step}" matches no existing step definition. '
                    "Rephrase it to match one of the provided step patterns exactly "
                    "(mind small wording differences like a missing \"of\"), or add the "
                    f"missing glue in a STEPDEF block under {glue_loc}. "
                    "If this is a route/path change, update the existing C# step definition "
                    "with the new URL rather than rewriting the feature step wording."
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
            if not _glue_patterns(glue.file_name.lstrip("./"), glue.content, glue.language):
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
    test_results_dir = repo / DOTNET_COMPONENT_DIR / "TestResults"
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

    For Java: runs `mvn test` on COMPONENT_DIR.
    For .NET: runs `dotnet test` on DOTNET_COMPONENT_DIR/DOTNET_TEST_PROJECT.
    
    Skips gracefully when tools aren't available or there's nothing to run."""
    repo = Path(state["repo_path"]).resolve()

    if not state.get("written_files"):
        return {"tests_passed": True, "test_failures": [],
                "test_report": "no files written; nothing to run"}

    project_type = state.get("project_type", "java")

    if project_type == "java":
        return _run_java_tests(repo, state)
    elif project_type == "ui":
        return _run_ui_tests(repo, state)
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

    project_file = str(repo / DOTNET_COMPONENT_DIR / DOTNET_TEST_PROJECT)
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



def _extract_ui_scenario_failures(repo: Path) -> list:
    """Parse the Cucumber-JS JSON report for failed/undefined UI scenarios."""
    report_path = repo / UI_COMPONENT_DIR / "reports" / "cucumber.json"
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
                        f'step "{step.get("keyword", "").strip()} {step.get("name")}" '
                        f'{res.get("status")}: {why[0] if why else ""}'
                    )
                    break
    return failures[:25]


def _run_ui_tests(repo: Path, state: TestGenState) -> TestGenState:
    """Execute front-end UI tests via npm (Vite build + Cucumber-JS + Playwright)."""
    ui_dir = repo / UI_COMPONENT_DIR
    npm = shutil.which("npm")
    if npm is None or not (ui_dir / "package.json").is_file():
        logger.warning(
            "npm not found or missing %s/package.json — skipping UI test execution",
            UI_COMPONENT_DIR,
        )
        return {"tests_passed": True, "test_failures": [],
                "test_report": "UI test execution skipped (npm or front-end package not available)"}

    logger.info("Running UI tests: npm test in %s", ui_dir)
    proc = subprocess.run(
        [npm, "test"],
        cwd=str(ui_dir), capture_output=True, text=True, timeout=TEST_TIMEOUT,
    )

    if proc.returncode == 0:
        logger.info("UI tests passed.")
        return {"tests_passed": True, "test_failures": [],
                "test_report": "all UI tests passed"}

    test_attempts = state.get("test_attempts", 0) + 1
    output = proc.stdout + "\n" + proc.stderr
    scenario_failures = _extract_ui_scenario_failures(repo)

    feedback: list = []
    if scenario_failures:
        feedback.append("UI SCENARIO FAILURES:")
        feedback += scenario_failures
    if not feedback:
        # Build/syntax error before Cucumber produced a report — feed back the tail.
        tail = "\n".join(output.splitlines()[-30:])
        feedback.append(
            "`npm test` failed before producing a scenario report (build, ESM/syntax, "
            "or selector error). Tail of the output:\n" + tail
        )

    logger.warning("UI test attempt %d failed (%d scenario failure(s))", test_attempts, len(scenario_failures))
    return {
        "tests_passed": False,
        "test_attempts": test_attempts,
        "test_failures": feedback,
        "test_report": f"{len(scenario_failures)} UI scenario failure(s) on attempt {test_attempts}",
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
    ado_work_item_id = state.get("ado_work_item_id") or os.environ.get("AZDO_WORK_ITEM_ID", "").strip()

    # Refinement mode: when re-running from QA feedback on an existing PR, commit the
    # updated tests onto that PR's branch instead of cutting a new one (set by the
    # label-triggered refine-tests workflow). Empty for the normal first-pass flow.
    refine_branch = os.environ.get("TESTGEN_PR_BRANCH", "").strip()
    branch_prefix = f"testgen/ado-{ado_work_item_id}-" if ado_work_item_id else "testgen/"
    branch = refine_branch or f"{branch_prefix}{head_sha}-{int(time.time())}"

    original_ref = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).strip()
    if refine_branch:
        _run(["git", "checkout", branch], cwd=repo)  # already exists; workflow checked it out
    else:
        _run(["git", "checkout", "-b", branch], cwd=repo)
    try:
        _run(["git", "add", *state["written_files"]], cwd=repo)
        staged = _run(["git", "diff", "--cached", "--name-only"], cwd=repo).strip()
        if not staged:
            logger.info("nothing staged after add; skipping PR")
            return {"pr_url": None, "skipped_reason": "no effective changes to commit"}
        verb = "refine" if refine_branch else "regenerate"
        commit_message = f"test: {verb} regression tests"
        if ado_work_item_id:
            commit_message = f"test: [ADO-{ado_work_item_id}] {verb} regression tests"
        _run(["git", "commit", "-m", commit_message + "\n\n" + generation.analysis_summary], cwd=repo)
        _run(["git", "push", "-u", "origin", branch], cwd=repo)

        # Refinement run: the PR already exists — pushing to its branch updates it
        # in place. No new PR, no metadata marker needed.
        if refine_branch:
            logger.info("Refinement pushed to existing PR branch %s", branch)
            return {"pr_url": None, "skipped_reason": f"updated existing PR branch {branch}"}

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

        if ado_work_item_id:
            title = f"[ADO-{ado_work_item_id}] {title}"

        # Machine-readable marker (invisible in rendered Markdown) so the
        # label-triggered refine workflow can recover what to regenerate against.
        base_sha = _run(["git", "rev-parse", state.get("resolved_base") or state["base_ref"]], cwd=repo).strip()
        head_full = _run(["git", "rev-parse", state["head_ref"]], cwd=repo).strip()
        meta_marker = (
            f"<!-- testgen-meta: base={base_sha} head={head_full} "
            f"project_type={state.get('project_type', 'java')} -->"
        )

        body_parts = [
            meta_marker,
            "## Auto-generated regression tests",
            "",
            generation.analysis_summary,
            "",
        ]
        if ado_work_item_id:
            body_parts.extend([
                "### Azure DevOps work item",
                state.get("ado_work_item_context", "Not available."),
                "",
            ])
        body_parts.extend([
            "### Test status",
            status,
            "",
            "### Impacted endpoints",
            endpoints,
            "",
            "### Files",
            *[f"- `{f}`" for f in state["written_files"]],
            "",
            "Please review the scenarios before merging. Regression runs automatically after merge.",
            ""
        ])
        body = "\n".join(body_parts)
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